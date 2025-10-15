from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List

import yaml
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from scripts.config_loader import GeneratorSettings
from scripts.utils.logger import setup_logger


class QualityGate:
    def __init__(self, settings: GeneratorSettings) -> None:
        self.settings = settings
        self.logger = setup_logger("quality", settings.logs_dir)

    def validate_article(self, artifact_path: Path, existing_texts: List[str]) -> bool:
        text = artifact_path.read_text(encoding="utf-8")
        if not self._validate_front_matter(text):
            return False
        body = self._extract_body(text)
        if not self._validate_length(body):
            return False
        if not self._validate_sections(body):
            return False
        if not self._validate_links(body):
            return False
        if not self._validate_ng_words(body):
            return False
        if not self._validate_images(text):
            return False
        if not self._validate_similarity(body, existing_texts):
            return False
        return True

    def _validate_front_matter(self, text: str) -> bool:
        match = re.match(r"---\n(.*?)\n---", text, re.DOTALL)
        if not match:
            self.logger.error("Front matter missing")
            return False
        try:
            fm = yaml.safe_load(match.group(1))
        except yaml.YAMLError as exc:
            self.logger.error("Front matter invalid: %s", exc)
            return False
        required_keys = {"title", "uuid", "summary", "tags", "publish_at"}
        if not required_keys.issubset(fm.keys()):
            self.logger.error("Front matter missing required keys")
            return False
        return True

    def _extract_body(self, text: str) -> str:
        parts = text.split("---\n", 2)
        if len(parts) < 3:
            return ""
        return parts[2]

    def _validate_length(self, body: str) -> bool:
        char_count = len(body)
        if char_count < self.settings.article.min_chars or char_count > self.settings.article.max_chars:
            self.logger.error("Article length constraint violated: %s chars", char_count)
            return False
        return True

    def _validate_sections(self, body: str) -> bool:
        for section in self.settings.article.required_sections:
            if section not in body:
                self.logger.error("Missing section: %s", section)
                return False
        return True

    def _validate_ng_words(self, body: str) -> bool:
        for word in self.settings.quality_gate.ng_words:
            if word in body:
                self.logger.error("Contains NG word: %s", word)
                return False
        return True

    def _validate_links(self, body: str) -> bool:
        links = re.findall(r"https?://\S+", body)
        invalid = [link for link in links if any(ord(ch) > 128 for ch in link)]
        if invalid and len(invalid) > self.settings.quality_gate.max_link_errors:
            self.logger.error("Invalid links detected: %s", invalid)
            return False
        return True

    def _validate_images(self, text: str) -> bool:
        fm_match = re.match(r"---\n(.*?)\n---", text, re.DOTALL)
        if not fm_match:
            return False
        fm = yaml.safe_load(fm_match.group(1))
        image_paths = []
        for key in ("thumbnail", "hero_image"):
            value = fm.get(key)
            if value:
                image_paths.append(value.replace('./', ''))
        for path in fm.get("internal_images", []):
            image_paths.append(path.replace('./', ''))
        for rel in image_paths:
            full_path = (self.settings.assets_dir.parent / rel).resolve()
            if not full_path.exists():
                self.logger.error("Missing image file: %s", full_path)
                return False
        return True

    def _validate_similarity(self, body: str, existing_texts: List[str]) -> bool:
        if not existing_texts:
            return True
        vectorizer = TfidfVectorizer()
        corpus = existing_texts + [body]
        tfidf = vectorizer.fit_transform(corpus)
        sims = cosine_similarity(tfidf[-1], tfidf[:-1]).flatten()
        max_sim = sims.max() if sims.size else 0.0
        if max_sim >= self.settings.dedupe.min_cosine_sim:
            self.logger.error("Similarity %.2f exceeds threshold", max_sim)
            return False
        return True

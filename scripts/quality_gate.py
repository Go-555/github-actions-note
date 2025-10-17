from __future__ import annotations

import re
from pathlib import Path
import unicodedata
from typing import Dict, List

import yaml
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
        if not self._validate_reject_phrases(body):
            return False
        if not self._validate_body_depth(body):
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
        normalized_body = unicodedata.normalize("NFKC", body or "")
        for section in self.settings.article.required_sections:
            normalized_section = unicodedata.normalize("NFKC", section)
            if normalized_section in normalized_body:
                continue
            heading_variant = unicodedata.normalize("NFKC", f"## {section}")
            if heading_variant in normalized_body:
                continue
            self.logger.error("Missing section: %s", section)
            return False
        return True

    def _validate_ng_words(self, body: str) -> bool:
        normalized_body = unicodedata.normalize("NFKC", body or "")
        for word in self.settings.quality_gate.ng_words:
            if word in body:
                self.logger.error("Contains NG word: %s", word)
                return False
            normalized_word = unicodedata.normalize("NFKC", word)
            if normalized_word and normalized_word in normalized_body:
                self.logger.error("Contains NG word: %s", word)
                return False
        return True

    def _validate_reject_phrases(self, body: str) -> bool:
        normalized_body = unicodedata.normalize("NFKC", body or "")
        for phrase in self.settings.quality_gate.reject_phrases:
            if phrase and phrase in body:
                self.logger.error("Contains rejected phrase: %s", phrase)
                return False
            normalized_phrase = unicodedata.normalize("NFKC", phrase)
            if normalized_phrase and normalized_phrase in normalized_body:
                self.logger.error("Contains rejected phrase: %s", phrase)
                return False
        return True

    def _validate_body_depth(self, body: str) -> bool:
        min_lines = self.settings.quality_gate.min_body_lines
        if min_lines:
            line_count = sum(1 for line in body.splitlines() if line.strip())
            if line_count < min_lines:
                self.logger.error("Body too shallow: %s lines < %s", line_count, min_lines)
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
        sims = [self._cosine_similarity(body, other) for other in existing_texts]
        max_sim = max(sims) if sims else 0.0
        if max_sim >= self.settings.dedupe.min_cosine_sim:
            self.logger.error("Similarity %.2f exceeds threshold", max_sim)
            return False
        return True

    def _cosine_similarity(self, text_a: str, text_b: str) -> float:
        tokens_a = self._tokenize(text_a)
        tokens_b = self._tokenize(text_b)
        if not tokens_a or not tokens_b:
            return 0.0
        vocab = set(tokens_a) | set(tokens_b)
        vec_a = [tokens_a.count(token) for token in vocab]
        vec_b = [tokens_b.count(token) for token in vocab]
        dot = sum(a * b for a, b in zip(vec_a, vec_b))
        norm_a = sum(a * a for a in vec_a) ** 0.5
        norm_b = sum(b * b for b in vec_b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    def _tokenize(self, text: str) -> List[str]:
        return [token for token in re.findall(r"[\w一-龥ぁ-んァ-ヴ]+", text.lower()) if token]

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

import yaml

from scripts.config_loader import GeneratorSettings
from scripts.utils.text import random_publish_at


@dataclass
class MarkdownArtifact:
    path: Path
    content: str
    front_matter: Dict[str, any]


class MarkdownBuilder:
    def __init__(self, settings: GeneratorSettings) -> None:
        self.settings = settings

    def build(self, slug: str, title: str, summary: str, tags: List[str], body: str, image_paths: Dict[str, Path], keyword: str) -> MarkdownArtifact:
        fm = self._front_matter(slug, title, summary, tags, image_paths, keyword)
        fm_yaml = yaml.safe_dump(fm, allow_unicode=True, sort_keys=False).strip()
        document = f"---\n{fm_yaml}\n---\n{body.strip()}\n"
        out_path = self.settings.queue.out_dir / f"{slug}.md"
        return MarkdownArtifact(path=out_path, content=document, front_matter=fm)

    def _front_matter(self, slug: str, title: str, summary: str, tags: List[str], image_paths: Dict[str, Path], keyword: str) -> Dict[str, any]:
        thumbnail = image_paths.get("thumbnail")
        hero = image_paths.get("hero")
        internals = image_paths.get("internals", [])
        def rel(p: Path | None) -> str:
            if not p:
                return ""
            rel_path = p.relative_to(self.settings.assets_dir.parent)
            return f"./{rel_path.as_posix()}"

        fm = {
            "title": title,
            "uuid": str(uuid.uuid4()),
            "summary": summary[:160],
            "tags": tags,
            "thumbnail": rel(thumbnail),
            "hero_image": rel(hero),
            "publish_at": random_publish_at(),
            "visibility": self.settings.defaults.visibility,
            "canonical_url": "",
            "series": self.settings.defaults.series,
            "notes": {
                "source_cluster": keyword,
                "generator_version": self.settings.generator_version,
            },
        }
        if internals:
            fm["internal_images"] = [rel(p) for p in internals]
        return fm

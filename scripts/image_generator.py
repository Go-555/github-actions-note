from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

import google.generativeai as genai

from scripts.config_loader import GeneratorSettings
from scripts.utils.logger import setup_logger


@dataclass
class GeneratedImages:
    thumbnail: Path
    hero: Path
    internals: List[Path]


class ImageGenerator:
    def __init__(self, settings: GeneratorSettings, api_key: str) -> None:
        self.settings = settings
        self.logger = setup_logger("images", settings.logs_dir)
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel(model_name="imagen-3.0")

    def generate(self, slug: str, briefs: Dict[str, any]) -> GeneratedImages:
        if not self.settings.images.enabled:
            return self._placeholder(slug)
        assets_dir = self.settings.assets_dir
        assets_dir.mkdir(parents=True, exist_ok=True)
        thumb = self._generate_one(briefs.get("thumbnail", ""), assets_dir / f"{slug}-thumb.jpg")
        hero = self._generate_one(briefs.get("hero", ""), assets_dir / f"{slug}-hero.jpg")
        internals: List[Path] = []
        for idx, brief in enumerate(briefs.get("internals", [])[: self.settings.images.internal_count], start=1):
            path = assets_dir / f"{slug}-internal{idx}.jpg"
            internals.append(self._generate_one(brief, path))
        return GeneratedImages(thumbnail=thumb, hero=hero, internals=internals)

    def _generate_one(self, prompt: str, path: Path) -> Path:
        try:
            if not prompt:
                raise ValueError("empty prompt")
            result = self.model.generate_images(
                prompt=prompt,
                number_of_images=1,
                size=f"{self.settings.images.width}x{self.settings.images.height}",
            )
            image_base64 = result.images[0].base64_data
            data = base64.b64decode(image_base64)
            path.write_bytes(data)
            self.logger.info("Generated image %s", path.name)
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("Image generation failed for %s: %s", path.name, exc)
            placeholder = self.settings.assets_dir / "placeholder.jpg"
            if not placeholder.exists():
                placeholder.write_bytes(b"")
            path.write_bytes(placeholder.read_bytes())
        return path

    def _placeholder(self, slug: str) -> GeneratedImages:
        assets_dir = self.settings.assets_dir
        assets_dir.mkdir(parents=True, exist_ok=True)
        placeholder = assets_dir / "placeholder.jpg"
        placeholder.write_bytes(b"")
        thumb = assets_dir / f"{slug}-thumb.jpg"
        hero = assets_dir / f"{slug}-hero.jpg"
        thumb.write_bytes(placeholder.read_bytes())
        hero.write_bytes(placeholder.read_bytes())
        return GeneratedImages(
            thumbnail=thumb,
            hero=hero,
            internals=[],
        )

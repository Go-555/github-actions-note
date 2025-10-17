from __future__ import annotations

import base64
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

try:
    # New SDK (recommended)
    from google import genai  # type: ignore
except Exception:  # pragma: no cover - fallback in case only old SDK exists
    genai = None  # Will be checked at runtime

# --------------------------------------------------------------------------------------
# Types
# --------------------------------------------------------------------------------------

@dataclass
class GeneratedImages:
    thumbnail: Path
    hero: Path
    internals: List[Path]


# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------

# 1x1 transparent PNG (valid) – avoids writing 0-byte files
_ONE_BY_ONE_PNG = base64.b64decode(
    b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMB/ebmN0kAAAAASUVORK5CYII="
)


def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def _setup_logger(name: str, logs_dir: Path) -> logging.Logger:
    _ensure_dir(logs_dir)
    logger = logging.getLogger(name)
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        fh = logging.FileHandler(logs_dir / f"{name}.log", encoding="utf-8")
        fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
        fh.setFormatter(fmt)
        logger.addHandler(fh)
        # Also emit to console in CI/Actions
        ch = logging.StreamHandler()
        ch.setFormatter(fmt)
        logger.addHandler(ch)
    return logger


# --------------------------------------------------------------------------------------
# Main class
# --------------------------------------------------------------------------------------

class ImageGenerator:
    """
    Gemini 2.5 (image-capable) バリアントを使って PNG/JPEG を生成。

    期待値:
      - settings.assets_dir: 画像の出力先ディレクトリ
      - settings.logs_dir:   ログ出力先
      - settings.images.enabled: bool – 生成を有効化するか
      - settings.images.internal_count: int – 内部画像の最大数

    依存:
      - 新SDK: `google.genai`（推奨）
        * 初期化: client = genai.Client(api_key=...)
        * 生成: client.models.generate_content(model=..., contents=[...])

    備考:
      - 例外時は 1x1 PNG のプレースホルダで埋める（0バイトは絶対に書かない）。
      - レート/一時エラーは指数バックオフで数回再試行。
    """

    MODEL_NAME = "gemini-2.5-flash-image"  # 画像生成向け

    def __init__(self, settings, api_key: Optional[str], dry_run: bool = False) -> None:
        self.settings = settings
        self.logger = _setup_logger("images", settings.logs_dir)
        self.dry_run = dry_run
        self._client = None

        if not dry_run and api_key:
            if genai is None:
                raise RuntimeError(
                    "The new Google GenAI SDK (`from google import genai`) is not available.\n"
                    "Install it: pip install google-genai"
                )
            # New SDK client
            self._client = genai.Client(api_key=api_key)

    # ----------------------------------------------------------------------------------
    # Public API
    # ----------------------------------------------------------------------------------

    def generate(self, slug: str, briefs: Dict[str, object]) -> GeneratedImages:
        assets_dir: Path = self.settings.assets_dir
        _ensure_dir(assets_dir)

        # Early exit if disabled or dry_run/no client
        if not getattr(self.settings.images, "enabled", True) or self.dry_run or not self._client:
            return self._placeholder(slug)

        thumb_prompt = str(briefs.get("thumbnail", "") or "")
        hero_prompt = str(briefs.get("hero", "") or "")
        internal_prompts = list(map(str, (briefs.get("internals", []) or [])))
        internal_prompts = internal_prompts[: int(getattr(self.settings.images, "internal_count", 0) or 0)]

        thumb_path = assets_dir / f"{slug}-thumb.png"
        hero_path = assets_dir / f"{slug}-hero.png"

        thumbnail = self._generate_one(thumb_prompt, thumb_path)
        hero = self._generate_one(hero_prompt, hero_path)

        internals: List[Path] = []
        for idx, brief in enumerate(internal_prompts, start=1):
            ipath = assets_dir / f"{slug}-internal{idx}.png"
            internals.append(self._generate_one(brief, ipath))

        return GeneratedImages(thumbnail=thumbnail, hero=hero, internals=internals)

    # ----------------------------------------------------------------------------------
    # Internal
    # ----------------------------------------------------------------------------------

    def _generate_one(self, prompt: str, path_hint: Path) -> Path:
        assets_dir: Path = self.settings.assets_dir
        _ensure_dir(assets_dir)

        if not prompt:
            self.logger.warning("Empty prompt supplied – writing placeholder: %s", path_hint.name)
            return self._write_placeholder(path_hint)

        # A little steer for simple, legible diagrams
        full_prompt = (
            f"{prompt}\n"
            "\n指示: シンプルで視認性の高い図解・サムネイル用の画像を生成してください。\n"
            "テキストは最小限、余白を取り、SNSサムネで潰れないデザインに。"
        )

        # Exponential backoff for transient errors
        max_tries = 4
        delay = 1.0
        last_exc: Optional[Exception] = None

        for attempt in range(1, max_tries + 1):
            try:
                resp = self._client.models.generate_content(
                    model=self.MODEL_NAME,
                    contents=[{"role": "user", "parts": [{"text": full_prompt}]}],
                )

                # Find first image part with inline_data
                part = self._pick_image_part(resp)
                if part is None:
                    raise RuntimeError("No image part returned from model response")

                mime = getattr(part.inline_data, "mime_type", "image/png") or "image/png"  # type: ignore[attr-defined]
                data_b64 = getattr(part.inline_data, "data", None)  # type: ignore[attr-defined]
                if not data_b64:
                    raise RuntimeError("Image part missing base64 data")

                raw = base64.b64decode(data_b64)

                # Decide final path by MIME if needed (prefer PNG)
                final_path = path_hint
                if mime.lower() == "image/jpeg" and path_hint.suffix.lower() != ".jpg":
                    final_path = path_hint.with_suffix(".jpg")
                elif mime.lower() == "image/png" and path_hint.suffix.lower() != ".png":
                    final_path = path_hint.with_suffix(".png")

                final_path.write_bytes(raw)
                self.logger.info("Generated image %s (mime=%s, bytes=%d)", final_path.name, mime, len(raw))
                return final_path

            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                self.logger.warning(
                    "Image generation attempt %d/%d failed for %s: %s",
                    attempt,
                    max_tries,
                    path_hint.name,
                    exc,
                )
                if attempt < max_tries:
                    time.sleep(delay)
                    delay *= 2

        # If all retries failed, write placeholder
        self.logger.error("Image generation failed – writing placeholder for %s: %s", path_hint.name, last_exc)
        return self._write_placeholder(path_hint)

    def _pick_image_part(self, resp) -> Optional[object]:
        """Extract the first image part with inline_data from a generate_content response."""
        try:
            for cand in getattr(resp, "candidates", []) or []:
                content = getattr(cand, "content", None)
                if not content:
                    continue
                for part in getattr(content, "parts", []) or []:
                    inline = getattr(part, "inline_data", None)
                    if inline and getattr(inline, "data", None):
                        return part
        except Exception:
            return None
        return None

    def _write_placeholder(self, target_path: Path) -> Path:
        """Write a valid 1x1 PNG placeholder next to requested name (preserve suffix)."""
        # Honor requested suffix; if it's not PNG/JPG, default to PNG suffix for correctness
        if target_path.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
            target_path = target_path.with_suffix(".png")

        target_path.write_bytes(_ONE_BY_ONE_PNG)
        return target_path

    # ----------------------------------------------------------------------------------
    # Placeholders for bulk (disabled/dry_run)
    # ----------------------------------------------------------------------------------

    def _placeholder(self, slug: str) -> GeneratedImages:
        assets_dir: Path = self.settings.assets_dir
        _ensure_dir(assets_dir)

        thumb = self._write_placeholder(assets_dir / f"{slug}-thumb.png")
        hero = self._write_placeholder(assets_dir / f"{slug}-hero.png")

        internals: List[Path] = []
        count = int(getattr(self.settings.images, "internal_count", 0) or 0)
        for idx in range(1, count + 1):
            internals.append(self._write_placeholder(assets_dir / f"{slug}-internal{idx}.png"))

        return GeneratedImages(thumbnail=thumb, hero=hero, internals=internals)

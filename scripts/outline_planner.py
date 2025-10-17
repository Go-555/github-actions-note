from __future__ import annotations

import json
import base64
from dataclasses import dataclass
from typing import Any, Dict, List

import google.generativeai as genai

from scripts.config_loader import GeneratorSettings
from scripts.utils.logger import setup_logger


@dataclass
class OutlinePlan:
    title: str
    summary: str
    outline: List[str]
    tags: List[str]
    image_briefs: Dict[str, Any]


class OutlinePlanner:
    def __init__(self, settings: GeneratorSettings, api_key: str, dry_run: bool = False) -> None:
        self.settings = settings
        self.logger = setup_logger("outline", settings.logs_dir)
        self.dry_run = dry_run
        if not dry_run and api_key:
            genai.configure(api_key=api_key)
            self.model = genai.GenerativeModel(
                model_name="models/gemini-2.5-flash",
                generation_config={
                    "temperature": 0.7,
                    "top_p": 0.9,
                },
            )
        else:
            self.model = None

    def create_plan(self, keyword: str, memo: str, references: List[str]) -> OutlinePlan:
        if self.dry_run or not self.model:
            return self._fallback_plan(keyword)

        schema = {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "summary": {"type": "string"},
                "outline": {"type": "array", "items": {"type": "string"}},
                "tags": {"type": "array", "items": {"type": "string"}},
                "image_briefs": {
                    "type": "object",
                    "properties": {
                        "thumbnail": {"type": "string"},
                        "hero": {"type": "string"},
                        "internals": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["thumbnail", "hero"],
                },
            },
            "required": ["title", "summary", "outline", "image_briefs"],
        }
        prompt = self._build_prompt(keyword, memo, references)
        try:
            response = self.model.generate_content(
                [prompt],
                generation_config={
                    "response_schema": schema,
                    "temperature": 0.6,
                    "top_p": 0.9,
                    "response_mime_type": "application/json",
                },
            )
            text = self._extract_text(response)
            data = json.loads(text or "{}")
            tags = data.get("tags") or self.settings.defaults.tags
            plan = OutlinePlan(
                title=data["title"],
                summary=data["summary"],
                outline=data["outline"],
                tags=tags,
                image_briefs=data["image_briefs"],
            )
            self.logger.info("Outline generated for '%s'", keyword)
            return plan
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("Outline generation fallback for %s: %s", keyword, exc)
            return self._fallback_plan(keyword)

    def _fallback_plan(self, keyword: str) -> OutlinePlan:
        sections = list(self.settings.article.required_sections)
        return OutlinePlan(
            title=f"{keyword}の最新動向",
            summary=f"{keyword} をテーマにした自動生成プランです。",
            outline=sections,
            tags=self.settings.defaults.tags,
            image_briefs={
                "thumbnail": f"{keyword} の主要トピックを端的に表現したクリーンな図解",
                "hero": f"{keyword} の課題と解決策を俯瞰できる図解",
                "internals": [f"{keyword} の実践手順を整理したフローチャート"],
            },
        )

    def _extract_text(self, response) -> str:
        if getattr(response, "text", None):
            return response.text
        candidates = getattr(response, "candidates", [])
        if not candidates:
            return ""
        parts = getattr(candidates[0].content, "parts", [])
        texts: List[str] = []
        for part in parts:
            value = getattr(part, "text", None)
            if value:
                texts.append(value)
                continue
            inline = getattr(part, "inline_data", None)
            if inline and getattr(inline, "data", None):
                try:
                    texts.append(base64.b64decode(inline.data).decode("utf-8"))
                    continue
                except Exception:  # noqa: BLE001
                    pass
            as_dict = getattr(part, "as_dict", None)
            if callable(as_dict):
                try:
                    dict_value = as_dict()
                    if isinstance(dict_value, dict) and "text" in dict_value:
                        texts.append(dict_value["text"])
                except Exception:  # noqa: BLE001
                    continue
        return "".join(texts)

    def _build_prompt(self, keyword: str, memo: str, references: List[str]) -> str:
        ref_text = "\n".join(references) if references else "なし"
        memo_text = memo or "入力メモなし"
        return (
            "あなたはSEOに強い編集者です。\n"
            f"キーワード: {keyword}\n"
            f"メモ内容:\n{memo_text}\n"
            f"参考資料一覧:\n{ref_text}\n"
            "note記事の構成案をJSONで作成してください。章立ては内容に合わせて臨機応変に対応してください。"
            "AI生成であることを匂わせない自然なタイトルと要約を作ってください。"
            "画像ブリーフはthumbnail, hero, internals(最大3)に分け、日本語で具体的に記述してください。"
        )

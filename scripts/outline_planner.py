from __future__ import annotations

import json
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
        if not dry_run:
            genai.configure(api_key=api_key)
            self.model = genai.GenerativeModel(
                model_name="gemini-1.5-pro-latest",
                generation_config={
                    "temperature": 0.7,
                    "top_p": 0.9,
                },
            )
        else:
            self.model = None

    def create_plan(self, keyword: str, memo: str, references: List[str]) -> OutlinePlan:
        if self.dry_run:
            summary = f"{keyword} をテーマにした自動生成テストサマリー"
            outline = self.settings.article.required_sections
            return OutlinePlan(
                title=f"{keyword}の最新動向",
                summary=summary,
                outline=list(outline),
                tags=self.settings.defaults.tags,
                image_briefs={
                    "thumbnail": f"{keyword} を象徴するクリーンなビジュアル",
                    "hero": f"{keyword} の課題と解決策を図解",
                    "internals": [f"{keyword} の実践手順を図解"],
                },
            )

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
        response = self.model.generate_content(
            [prompt],
            generation_config={
                "response_schema": schema,
                "temperature": 0.6,
                "top_p": 0.9,
            },
        )
        data = json.loads(response.text)
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

    def _build_prompt(self, keyword: str, memo: str, references: List[str]) -> str:
        ref_text = "\n".join(references) if references else "なし"
        memo_text = memo or "入力メモなし"
        return (
            "あなたはSEOに強い編集者です。\n"
            f"キーワード: {keyword}\n"
            f"メモ内容:\n{memo_text}\n"
            f"参考資料一覧:\n{ref_text}\n"
            "note記事の構成案をJSONで作成してください。章立ては背景と課題、結論（先出し）、手順、よくある失敗と対策、事例・効果、まとめ（CTA）、参考リンクを含めてください。"
            "AI生成であることを匂わせない自然なタイトルと要約を作ってください。"
            "画像ブリーフはthumbnail, hero, internals(最大3)に分け、日本語で具体的に記述してください。"
        )

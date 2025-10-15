from __future__ import annotations

from dataclasses import dataclass
from typing import List

import google.generativeai as genai

from scripts.config_loader import GeneratorSettings
from scripts.utils.logger import setup_logger


@dataclass
class GeneratedArticle:
    lead: str
    sections: List[str]
    references: List[str]
    body_markdown: str


class ArticleGenerator:
    def __init__(self, settings: GeneratorSettings, api_key: str) -> None:
        self.settings = settings
        self.logger = setup_logger("article", settings.logs_dir)
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel(
            model_name="gemini-1.5-pro-latest",
            generation_config={
                "temperature": 0.65,
                "top_p": 0.9,
                "max_output_tokens": 8192,
            },
        )

    def generate(self, keyword: str, memo: str, plan: dict) -> GeneratedArticle:
        prompt = self._build_prompt(keyword, memo, plan)
        response = self.model.generate_content([prompt])
        text = response.text
        self.logger.info("Generated article body for '%s'", keyword)
        return GeneratedArticle(
            lead="",
            sections=self.settings.article.required_sections,
            references=[],
            body_markdown=text,
        )

    def _build_prompt(self, keyword: str, memo: str, plan: dict) -> str:
        sections = "\n".join(f"- {item}" for item in plan["outline"])
        return (
            "あなたはプロのSEOライターです。\n"
            f"キーワード: {keyword}\n"
            f"構成案:\n{sections}\n"
            f"メモ:\n{memo or 'なし'}\n"
            "以下の制約を守ってMarkdown本文を書いてください。\n"
            "- 文字数はおよそ 3,000～5,000 字\n"
            "- リード文（100～200字）を先頭に書く\n"
            "- 背景と課題, 結論（先出し）, 手順, よくある失敗と対策, 事例・効果, まとめ（CTA), 参考リンク の順に H2 見出しを配置する\n"
            "- 必要に応じて H3/H4 を使い、読者に実務で役立つ洞察を提供する\n"
            "- 誇大表現や根拠のない断定は避け、一次情報や具体例を挙げる\n"
            "- 参考リンクは文末のリストで提示する\n"
            "- 画像を差し込みたい箇所には '![代替テキスト](./assets/placeholder.jpg)' の形式で記載する（後で差し替える）\n"
            "- 日本語で書く\n"
        )

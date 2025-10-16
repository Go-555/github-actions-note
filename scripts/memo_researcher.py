from __future__ import annotations

import base64
import json
import os
from datetime import datetime
from pathlib import Path
from typing import List

import google.generativeai as genai

from scripts.config_loader import GeneratorSettings
from scripts.utils.logger import setup_logger
from scripts.utils.text import generate_slug, write_text


class MemoResearcher:
    def __init__(self, settings: GeneratorSettings, api_key: str | None, dry_run: bool = False) -> None:
        self.settings = settings
        self.logger = setup_logger("memo", settings.logs_dir)
        self.dry_run = dry_run
        self.api_key = api_key
        if not dry_run and api_key:
            genai.configure(api_key=api_key)
            self.model = genai.GenerativeModel(
                model_name="models/gemini-2.5-flash",
                generation_config={"temperature": 0.8, "top_p": 0.9},
            )
        else:
            self.model = None
        self.settings.memos.inbox_dir.mkdir(parents=True, exist_ok=True)
        self.settings.memos.trash_dir.mkdir(parents=True, exist_ok=True)

    def ensure_inventory(self, target_count: int) -> None:
        inbox = self.settings.memos.inbox_dir
        existing = list(inbox.glob("*.md"))
        desired = min(self.settings.memos.daily_target, target_count)
        missing = desired - len(existing)
        if missing <= 0:
            self.logger.info("Memo inventory sufficient: %s", len(existing))
            return
        memos = self._generate_memos(missing)
        for memo in memos:
            self._write_memo(memo)
        self.logger.info("Added %s memos to inbox", len(memos))

    def archive_memo(self, memo_path: Path) -> None:
        if not memo_path or not memo_path.exists():
            return
        target = self.settings.memos.trash_dir / memo_path.name
        try:
            memo_path.rename(target)
            self.logger.info("Moved memo %s to trash", memo_path.name)
        except OSError as exc:
            self.logger.warning("Failed to move memo %s: %s", memo_path, exc)

    def _generate_memos(self, count: int) -> List[dict]:
        if self.dry_run or not self.model:
            return [
                {
                    "title": f"生成AIリサーチ {i+1}",
                    "summary": "ドライラン用のテストメモ。",
                    "bullets": [
                        "最新動向のダミー項目",
                        "ユースケースのダミー項目",
                        "リスクと対策のダミー項目",
                    ],
                }
                for i in range(count)
            ]
        schema = {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "summary": {"type": "string"},
                    "bullets": {
                        "type": "array",
                        "items": {"type": "string"},
                        "maxItems": 5,
                    },
                },
                "required": ["title", "summary", "bullets"],
            },
        }
        prompt = (
            "あなたは技術調査担当です。キーワード '生成AI' に関する最新トピックを"
            f"{count} 件まとめ、JSON 配列で返してください。各要素は title, summary, bullets(3項目) を含むオブジェクトとします。"
        )
        memos: List[dict] = []
        try:
            response = self.model.generate_content(
                [prompt],
                generation_config={
                    "response_schema": schema,
                    "response_mime_type": "application/json",
                },
            )
            text = self._extract_text(response)
            memos = json.loads(text or "[]")
        except Exception:  # noqa: BLE001
            self.logger.warning("Memo generation fallback")
        if not isinstance(memos, list):
            memos = []
        if len(memos) < count:
            memos.extend(self._dummy_memos(count - len(memos)))
        return memos[:count]

    def _dummy_memos(self, count: int) -> List[dict]:
        return [
            {
                "title": f"生成AIトピック（補完） {i+1}",
                "summary": "生成AI市場や運用に関する最新情報を確認してください。",
                "bullets": [
                    "最新のリリース情報をウォッチ",
                    "導入企業の成功事例を調査",
                    "リスクとガバナンスの最新動向を整理",
                ],
            }
            for i in range(count)
        ]

    def _extract_text(self, response) -> str:
        if getattr(response, "text", None):
            return response.text
        candidates = getattr(response, "candidates", [])
        if not candidates:
            return ""
        parts = getattr(candidates[0].content, "parts", [])
        texts = []
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

    def _write_memo(self, memo: dict) -> None:
        title = memo.get("title") or "生成AIトピック"
        summary = memo.get("summary", "")
        bullets = memo.get("bullets", [])
        slug = generate_slug(f"{title}-{datetime.now().strftime('%Y%m%d%H%M%S')}")
        path = self.settings.memos.inbox_dir / f"{slug}.md"
        content_lines = [f"# {title}", "", summary, ""]
        for bullet in bullets:
            content_lines.append(f"- {bullet}")
        write_text(path, "\n".join(content_lines) + "\n")

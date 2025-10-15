from __future__ import annotations

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
                model_name="gemini-1.5-pro-latest",
                generation_config={"temperature": 0.8, "top_p": 0.9},
            )
        else:
            self.model = None
        self.settings.memos.inbox_dir.mkdir(parents=True, exist_ok=True)
        self.settings.memos.trash_dir.mkdir(parents=True, exist_ok=True)

    def ensure_inventory(self) -> None:
        inbox = self.settings.memos.inbox_dir
        existing = list(inbox.glob("*.md"))
        missing = self.settings.memos.daily_target - len(existing)
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
        prompt = (
            "あなたは技術調査担当です。キーワード '生成AI' に関する今週の注目トピックを"
            f"{count} 件まとめ、JSON 形式で返してください。各件は title, summary, bullets(3項目) を持つオブジェクトとします。"
        )
        response = self.model.generate_content([prompt])
        memos: List[dict] = []
        try:
            text = response.text or ""
            memos = json.loads(text)
        except Exception:  # noqa: BLE001
            self.logger.warning("Memo generation fallback")
        if not isinstance(memos, list):
            memos = []
        if len(memos) < count:
            memos.extend(self._generate_memos(count - len(memos)))
        return memos[:count]

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

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from scripts.config_loader import GeneratorSettings


def _extract_topics_from_memo(content: str, fallback: str) -> List[str]:
    topics: List[str] = []
    seen = set()
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        heading = None
        if stripped.startswith("#"):
            heading = stripped.lstrip("#").strip()
        elif stripped.startswith("-") or stripped.startswith("*"):
            heading = stripped.lstrip("-* ").strip()
        if heading:
            normalized = heading.lower()
            if normalized not in seen:
                seen.add(normalized)
                topics.append(heading)
    if not topics:
        first_line = fallback.strip()
        if first_line:
            topics.append(first_line)
    if not topics:
        topics.append("生成AI 最新動向")
    return topics


@dataclass
class GenerationTask:
    keyword: str
    memo_path: Optional[Path]
    memo_content: str
    reference_paths: List[Path]


class TaskLoader:
    def __init__(self, settings: GeneratorSettings) -> None:
        self.settings = settings
        self.references = sorted((Path.cwd() / "inputs" / "research").glob('*'))

    def load_tasks(self, limit: int) -> List[GenerationTask]:
        memos = self._list_memos()
        tasks: List[GenerationTask] = []
        for memo_path in memos:
            memo_content = memo_path.read_text(encoding="utf-8")
            topics = _extract_topics_from_memo(memo_content, memo_path.stem)
            for topic in topics:
                tasks.append(
                    GenerationTask(
                        keyword=topic,
                        memo_path=memo_path,
                        memo_content=memo_content,
                        reference_paths=self.references,
                    )
                )
        return tasks[:limit]

    def _list_memos(self) -> List[Path]:
        inbox = self.settings.memos.inbox_dir
        inbox.mkdir(parents=True, exist_ok=True)
        memo_files = sorted(inbox.glob('*.md'), key=lambda p: p.stat().st_mtime)
        return memo_files

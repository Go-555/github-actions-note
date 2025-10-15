from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from scripts.config_loader import GeneratorSettings


def _derive_keyword_from_memo(path: Path, content: str) -> str:
    for line in content.splitlines():
        stripped = line.strip().lstrip('#').strip()
        if stripped:
            return stripped
    return path.stem


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

    def load_tasks(self) -> List[GenerationTask]:
        memos = self._list_memos()
        tasks: List[GenerationTask] = []
        for memo_path in memos:
            memo_content = memo_path.read_text(encoding="utf-8")
            keyword = _derive_keyword_from_memo(memo_path, memo_content)
            tasks.append(
                GenerationTask(
                    keyword=keyword,
                    memo_path=memo_path,
                    memo_content=memo_content,
                    reference_paths=self.references,
                )
            )
        limit = self.settings.concurrency.per_run_batch
        return tasks[:limit]

    def _list_memos(self) -> List[Path]:
        inbox = self.settings.memos.inbox_dir
        inbox.mkdir(parents=True, exist_ok=True)
        memo_files = sorted(inbox.glob('*.md'), key=lambda p: p.stat().st_mtime)
        return memo_files

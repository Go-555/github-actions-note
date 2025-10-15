from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional

from scripts.config_loader import GeneratorSettings


@dataclass
class GenerationTask:
    keyword: str
    memo_path: Optional[Path]
    memo_content: str
    reference_paths: List[Path]


class TaskLoader:
    def __init__(self, settings: GeneratorSettings) -> None:
        self.settings = settings
        self.root = Path.cwd()

    def load_tasks(self) -> List[GenerationTask]:
        keywords = self._load_keywords()
        memos = self._load_memos()
        reference = self._collect_reference_files()
        tasks: List[GenerationTask] = []
        for keyword in keywords:
            memo_path = memos.get(keyword)
            memo_content = memo_path.read_text(encoding="utf-8") if memo_path else ""
            tasks.append(
                GenerationTask(
                    keyword=keyword,
                    memo_path=memo_path,
                    memo_content=memo_content,
                    reference_paths=reference,
                )
            )
        return tasks[: self.settings.concurrency.per_run_batch]

    def _load_keywords(self) -> List[str]:
        folder = self.root / "inputs" / "keywords"
        keywords: List[str] = []
        for path in sorted(folder.glob("*.txt")):
            for line in path.read_text(encoding="utf-8").splitlines():
                normalized = line.strip()
                if normalized:
                    keywords.append(normalized)
        return keywords

    def _load_memos(self) -> dict[str, Path]:
        folder = self.root / "inputs" / "memos"
        mapping: dict[str, Path] = {}
        for path in sorted(folder.glob("*.md")):
            key = path.stem
            mapping[key] = path
        for path in sorted(folder.glob("*.txt")):
            key = path.stem
            mapping[key] = path
        return mapping

    def _collect_reference_files(self) -> List[Path]:
        folder = self.root / "inputs" / "research"
        return sorted(folder.glob("*"))

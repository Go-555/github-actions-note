from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict

from scripts.config_loader import GeneratorSettings
from scripts.utils.logger import setup_logger
from scripts.utils.text import write_text


@dataclass
class QueueResult:
    markdown_path: Path
    assets: Dict[str, Path]


class QueueWriter:
    def __init__(self, settings: GeneratorSettings) -> None:
        self.settings = settings
        self.logger = setup_logger("queue", settings.logs_dir)

    def save(self, artifact_path: Path, content: str, assets: Dict[str, Path]) -> QueueResult:
        self.settings.queue.out_dir.mkdir(parents=True, exist_ok=True)
        write_text(artifact_path, content)
        self.logger.info("Queued article %s", artifact_path.name)
        return QueueResult(markdown_path=artifact_path, assets=assets)

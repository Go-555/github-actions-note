from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

import yaml


@dataclass
class RetryConfig:
    max_attempts: int = 3
    base_delay_sec: int = 20
    max_delay_sec: int = 90


@dataclass
class ArticleConfig:
    min_chars: int
    max_chars: int
    required_sections: List[str]
    lead_min_chars: int
    lead_max_chars: int


@dataclass
class ImageConfig:
    enabled: bool
    style: str
    internal_count: int
    width: int
    height: int


@dataclass
class MemoConfig:
    inbox_dir: Path
    trash_dir: Path
    daily_target: int
    research_keyword: str


@dataclass
class QueueConfig:
    out_dir: Path
    posted_dir: Path


@dataclass
class DedupeConfig:
    min_cosine_sim: float


@dataclass
class DefaultsConfig:
    tags: List[str]
    visibility: str
    series: str


@dataclass
class ConcurrencyConfig:
    daily_limit: int
    per_run_batch: int
    max_parallel: int
    jitter_sec: List[int]


@dataclass
class QualityGateConfig:
    ng_words: List[str] = field(default_factory=list)
    max_link_errors: int = 0


@dataclass
class GeneratorSettings:
    generator_version: str
    locale: str
    memos: MemoConfig
    article: ArticleConfig
    images: ImageConfig
    queue: QueueConfig
    assets_dir: Path
    logs_dir: Path
    concurrency: ConcurrencyConfig
    dedupe: DedupeConfig
    defaults: DefaultsConfig
    retry: RetryConfig
    quality_gate: QualityGateConfig


class ConfigLoader:
    def __init__(self, root: Path) -> None:
        self.root = root

    def load(self, path: Path | None = None) -> GeneratorSettings:
        cfg_path = path if path else self.root / "config" / "config.yaml"
        data = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
        return self._parse(data)

    def _parse(self, data: Dict[str, Any]) -> GeneratorSettings:
        article = ArticleConfig(**data["article"])
        images = ImageConfig(**data["images"])
        memos = MemoConfig(
            inbox_dir=self.root / data["memos"]["inbox_dir"],
            trash_dir=self.root / data["memos"]["trash_dir"],
            daily_target=data["memos"]["daily_target"],
            research_keyword=data["memos"]["research_keyword"],
        )
        queue = QueueConfig(
            out_dir=self.root / data["queue"]["out_dir"],
            posted_dir=self.root / data["queue"]["posted_dir"],
        )
        concurrency = ConcurrencyConfig(**data["concurrency"])
        dedupe = DedupeConfig(**data["dedupe"])
        defaults = DefaultsConfig(**data["defaults"])
        retry = RetryConfig(**data.get("retry", {}))
        quality_gate = QualityGateConfig(**data.get("quality_gate", {}))
        return GeneratorSettings(
            generator_version=data["generator_version"],
            locale=data.get("locale", "ja-JP"),
            memos=memos,
            article=article,
            images=images,
            queue=queue,
            assets_dir=self.root / data["assets_dir"],
            logs_dir=self.root / data["logs"]["dir"],
            concurrency=concurrency,
            dedupe=dedupe,
            defaults=defaults,
            retry=retry,
            quality_gate=quality_gate,
        )

    def dump_example(self, output: Path) -> None:
        settings = self.load()
        output.write_text(json.dumps(settings.__dict__, indent=2, default=str), encoding="utf-8")

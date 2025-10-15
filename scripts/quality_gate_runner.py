from __future__ import annotations

import sys
from pathlib import Path

from scripts.config_loader import ConfigLoader
from scripts.quality_gate import QualityGate


def main() -> int:
    root = Path.cwd()
    config = ConfigLoader(root).load()
    gate = QualityGate(config)
    queue_files = list(config.queue.out_dir.glob("*.md"))
    if not queue_files:
        print("No queue articles to validate")
        return 0
    texts = [path.read_text(encoding="utf-8") for path in queue_files]
    ok = True
    for idx, path in enumerate(queue_files):
        body_texts = texts[:idx] + texts[idx + 1 :]
        if not gate.validate_article(path, body_texts):
            print(f"Validation failed: {path}")
            ok = False
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import sys
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.config_loader import ConfigLoader
from scripts.quality_gate import QualityGate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run quality gate checks")
    parser.add_argument("--file", help="Validate a single markdown file")
    args = parser.parse_args(argv)

    root = Path.cwd()
    config = ConfigLoader(root).load()
    gate = QualityGate(config)
    if args.file:
        target = Path(args.file)
        if not target.exists():
            print(f"Target file not found: {target}")
            return 1
        other_texts: list[str] = []
        for sibling in config.queue.out_dir.glob("*.md"):
            if sibling.resolve() != target.resolve():
                other_texts.append(sibling.read_text(encoding="utf-8"))
        for posted in config.queue.posted_dir.glob("*.md"):
            other_texts.append(posted.read_text(encoding="utf-8"))
        success = gate.validate_article(target, other_texts)
        if not success:
            print(f"Validation failed: {target}")
        return 0 if success else 1

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
    raise SystemExit(main(sys.argv[1:]))

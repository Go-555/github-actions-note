from __future__ import annotations

import os
import traceback
from pathlib import Path
from typing import Dict, List

import yaml

from scripts.article_generator import ArticleGenerator
from scripts.config_loader import ConfigLoader
from scripts.image_generator import ImageGenerator
from scripts.markdown_builder import MarkdownBuilder
from scripts.outline_planner import OutlinePlanner
from scripts.queue_writer import QueueWriter
from scripts.quality_gate import QualityGate
from scripts.task_loader import TaskLoader
from scripts.utils.logger import append_jsonl, setup_logger
from scripts.utils.text import generate_slug


def load_existing_texts(queue_dir: Path, posted_dir: Path) -> List[str]:
    texts: List[str] = []
    for path in list(queue_dir.glob("*.md")) + list(posted_dir.glob("*.md")):
        texts.append(path.read_text(encoding="utf-8"))
    return texts


def main() -> int:
    root = Path.cwd()
    config = ConfigLoader(root).load()
    logger = setup_logger("batch", config.logs_dir)

    gemini_key = os.environ.get("GEMINI_API_KEY")
    if not gemini_key:
        logger.error("GEMINI_API_KEY is not set")
        return 1
    image_key = os.environ.get("IMAGE_API_KEY", gemini_key)

    task_loader = TaskLoader(config)
    tasks = task_loader.load_tasks()
    if not tasks:
        logger.info("No tasks to process")
        return 0

    outline = OutlinePlanner(config, gemini_key)
    article_generator = ArticleGenerator(config, gemini_key)
    image_generator = ImageGenerator(config, image_key)
    markdown_builder = MarkdownBuilder(config)
    queue_writer = QueueWriter(config)
    quality_gate = QualityGate(config)

    existing_texts = load_existing_texts(config.queue.out_dir, config.queue.posted_dir)

    success = 0
    failure = 0
    for task in tasks[: config.concurrency.per_run_batch]:
        log_payload: Dict[str, str] = {"keyword": task.keyword}
        try:
            reference_contents = []
            for ref_path in task.reference_paths:
                try:
                    reference_contents.append(ref_path.read_text(encoding="utf-8"))
                except Exception:  # noqa: BLE001
                    reference_contents.append(ref_path.name)
            plan = outline.create_plan(task.keyword, task.memo_content, reference_contents)
            slug = generate_slug(plan.title)
            images = image_generator.generate(slug, plan.image_briefs)
            image_paths = {
                "thumbnail": images.thumbnail,
                "hero": images.hero,
                "internals": images.internals,
            }
            article = article_generator.generate(task.keyword, task.memo_content, plan.__dict__)
            artifact = markdown_builder.build(
                slug=slug,
                title=plan.title,
                summary=plan.summary,
                tags=plan.tags,
                body=article.body_markdown,
                image_paths=image_paths,
                keyword=task.keyword,
            )
            queue_writer.save(artifact.path, artifact.content, image_paths)
            if not quality_gate.validate_article(artifact.path, existing_texts):
                logger.error("Quality gate failed for %s", artifact.path)
                artifact.path.unlink(missing_ok=True)
                failure += 1
                continue
            success += 1
            existing_texts.append(artifact.content)
            log_payload["status"] = "success"
            log_payload["path"] = str(artifact.path)
        except Exception as exc:  # noqa: BLE001
            logger.error("Task failed for %s: %s", task.keyword, exc)
            logger.debug(traceback.format_exc())
            log_payload["status"] = "error"
            log_payload["error"] = str(exc)
            failure += 1
        finally:
            append_jsonl(config.logs_dir / "run.jsonl", log_payload)

    logger.info("Batch finished: success=%s failure=%s", success, failure)
    return 0 if failure == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

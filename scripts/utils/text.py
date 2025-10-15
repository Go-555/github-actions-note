from __future__ import annotations

import random
import string
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, List

from dateutil import tz
from slugify import slugify


def generate_slug(base: str) -> str:
    normalized = slugify(base, lowercase=True)
    return normalized or random_suffix()


def random_suffix(length: int = 6) -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=length))


def ensure_sections_present(content: str, sections: Iterable[str]) -> bool:
    lowered = content.lower()
    return all(section.lower() in lowered for section in sections)


def random_publish_at(jst: bool = True, start_hour: int = 9, end_hour: int = 22) -> str:
    tzinfo = timezone(timedelta(hours=9)) if jst else tz.UTC
    base = datetime.now(tz=tzinfo) + timedelta(days=1)
    random_hour = random.randint(start_hour, end_hour)
    random_minute = random.randint(0, 59)
    randomized = base.replace(hour=random_hour, minute=random_minute, second=0, microsecond=0)
    return randomized.isoformat()


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")

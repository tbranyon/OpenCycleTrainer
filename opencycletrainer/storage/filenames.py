from __future__ import annotations

import re
from datetime import datetime


_INVALID_NAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WHITESPACE = re.compile(r"\s+")


def normalize_workout_name(workout_name: str) -> str:
    cleaned = _INVALID_NAME_CHARS.sub("", workout_name.strip())
    cleaned = _WHITESPACE.sub("_", cleaned)
    return cleaned or "Workout"


def build_activity_filename(workout_name: str, when: datetime, extension: str) -> str:
    ext = extension.strip().lstrip(".")
    if not ext:
        raise ValueError("File extension must not be empty.")

    normalized_name = normalize_workout_name(workout_name)
    return f"{normalized_name}_{when:%Y%m%d}_{when:%H%M}.{ext}"


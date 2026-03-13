from __future__ import annotations

import json
import logging
from pathlib import Path

from opencycletrainer.storage.paths import get_data_dir

_logger = logging.getLogger(__name__)
_HISTORY_FILENAME = "strava_upload_history.json"


def _history_path() -> Path:
    return get_data_dir() / _HISTORY_FILENAME


def _entry_key(fit_path: Path) -> str:
    """Return a stable dedupe key based on filename and file size."""
    try:
        size = fit_path.stat().st_size
    except OSError:
        size = 0
    return f"{fit_path.name}:{size}"


def is_already_uploaded(fit_path: Path, *, history_path: Path | None = None) -> bool:
    """Return True if this FIT file has a recorded successful upload."""
    path = history_path if history_path is not None else _history_path()
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return _entry_key(fit_path) in set(data.get("uploads", []))
    except Exception:  # noqa: BLE001
        return False


def record_upload(fit_path: Path, *, history_path: Path | None = None) -> None:
    """Record a successful upload so duplicates can be detected later."""
    path = history_path if history_path is not None else _history_path()
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
        else:
            data = {"uploads": []}
        key = _entry_key(fit_path)
        if key not in data["uploads"]:
            data["uploads"].append(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:  # noqa: BLE001
        _logger.warning("Failed to record Strava upload history for %s", fit_path.name)

from __future__ import annotations

import json
from pathlib import Path

from .paths import ensure_dir, get_blocks_file_path


def load_blocks(path: Path | None = None) -> dict[str, str]:
    """Load reusable workout blocks as a name -> builder-text map.

    Returns an empty map if the file is missing, empty, or unparseable.
    """
    blocks_path = path or get_blocks_file_path()
    if not blocks_path.exists():
        return {}

    raw_data = blocks_path.read_text(encoding="utf-8")
    if not raw_data.strip():
        return {}

    try:
        data = json.loads(raw_data)
    except json.JSONDecodeError:
        return {}

    if not isinstance(data, dict):
        return {}

    return {str(name): str(text) for name, text in data.items()}


def save_blocks(blocks: dict[str, str], path: Path | None = None) -> Path:
    blocks_path = path or get_blocks_file_path()
    ensure_dir(blocks_path.parent)
    blocks_path.write_text(json.dumps(blocks, indent=2), encoding="utf-8")
    return blocks_path

from __future__ import annotations

import logging
from pathlib import Path

from .storage.paths import ensure_dir, get_log_file_path


def configure_logging(log_path: Path | None = None) -> Path:
    target_log_path = log_path or get_log_file_path()
    ensure_dir(target_log_path.parent)

    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    has_console = any(getattr(handler, "name", "") == "oct_console" for handler in logger.handlers)
    has_file = any(getattr(handler, "name", "") == "oct_file" for handler in logger.handlers)

    if not has_console:
        console_handler = logging.StreamHandler()
        console_handler.name = "oct_console"
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    if not has_file:
        file_handler = logging.FileHandler(target_log_path, encoding="utf-8")
        file_handler.name = "oct_file"
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return target_log_path

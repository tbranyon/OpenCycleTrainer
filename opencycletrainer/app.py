from __future__ import annotations

import logging
from pathlib import Path

from nicegui import app, ui

from .logging_config import configure_logging
from .storage.paths import ensure_dir, get_config_dir, get_data_dir, get_settings_file_path
from .storage.settings import AppSettings, load_settings
from . import state

_RES_DIR = Path(__file__).parent.parent / "res"


def _initialize_environment() -> AppSettings:
    ensure_dir(get_config_dir())
    ensure_dir(get_data_dir())
    configure_logging()
    settings = load_settings(get_settings_file_path())
    logging.getLogger(__name__).info("Settings loaded from %s", get_settings_file_path())
    return settings


def main() -> int:
    settings = _initialize_environment()
    state.init(settings, get_settings_file_path())

    # Serve app resources (logo, etc.) as static files
    if _RES_DIR.is_dir():
        app.add_static_files("/res", str(_RES_DIR))

    # Register all pages — must happen before ui.run()
    from .ui.pages import register_all
    register_all()

    ui.run(
        native=True,
        title="OpenCycleTrainer",
        window_size=(1024, 720),
        storage_secret="oct-native-storage-2024",
        reload=False,
    )
    return 0

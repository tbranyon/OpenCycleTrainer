from __future__ import annotations

import logging
import sys

from PySide6.QtWidgets import QApplication

from .logging_config import configure_logging
from .storage.paths import ensure_dir, get_config_dir, get_data_dir, get_settings_file_path
from .storage.settings import AppSettings, load_settings
from .ui.main_window import MainWindow


def initialize_environment() -> AppSettings:
    ensure_dir(get_config_dir())
    ensure_dir(get_data_dir())
    configure_logging()
    settings = load_settings(get_settings_file_path())
    logging.getLogger(__name__).info("Settings loaded from %s", get_settings_file_path())
    return settings


def main() -> int:
    settings = initialize_environment()
    app = QApplication(sys.argv)
    window = MainWindow(settings=settings, settings_path=get_settings_file_path())
    window.show()
    return app.exec()

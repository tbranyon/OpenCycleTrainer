from __future__ import annotations

import os
import shutil
from pathlib import Path

from PySide6.QtWidgets import QApplication

from opencycletrainer.storage.settings import AppSettings, load_settings, save_settings
from opencycletrainer.ui.main_window import MainWindow
from opencycletrainer.ui.settings_screen import SettingsScreen
from opencycletrainer.ui.tile_config import MAX_CONFIGURABLE_TILES, TILE_OPTIONS


def _get_or_create_qapp() -> QApplication:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _test_settings_path() -> Path:
    folder = Path.cwd() / ".tmp_runtime" / "settings_screen_tests"
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "settings.json"


def test_settings_screen_persists_basic_fields_and_tile_limit():
    _get_or_create_qapp()
    settings_path = _test_settings_path()
    save_settings(AppSettings(), settings_path)

    screen = SettingsScreen(settings_path=settings_path)
    screen.ftp_spinbox.setValue(315)
    screen.lead_time_spinbox.setValue(7)
    screen.opentrueup_checkbox.setChecked(True)
    screen.display_units_combo.setCurrentText("Imperial")
    screen.default_behavior_combo.setCurrentText("Free Ride Mode")

    all_tile_keys = [key for key, _ in TILE_OPTIONS]
    for key in all_tile_keys[: MAX_CONFIGURABLE_TILES + 1]:
        screen.set_tile_selected(key, True)

    screen.save_current_settings()
    persisted = load_settings(settings_path)

    assert persisted.ftp == 315
    assert persisted.lead_time == 7
    assert persisted.opentrueup_enabled is True
    assert persisted.display_units == "imperial"
    assert persisted.default_workout_behavior == "free_ride_mode"
    assert len(persisted.tile_selections) == MAX_CONFIGURABLE_TILES
    assert all_tile_keys[MAX_CONFIGURABLE_TILES] not in persisted.tile_selections


def test_main_window_applies_settings_screen_tile_updates_to_workout_screen():
    _get_or_create_qapp()
    settings_path = _test_settings_path()
    settings = AppSettings(tile_selections=["heart_rate"])
    save_settings(settings, settings_path)

    window = MainWindow(settings=settings, settings_path=settings_path)
    assert window.workout_screen.get_selected_tile_keys() == ["heart_rate"]

    window.settings_screen.set_tile_selected("workout_avg_power", True)
    window.settings_screen.save_current_settings()

    assert window.workout_screen.get_selected_tile_keys() == ["heart_rate", "workout_avg_power"]
    persisted = load_settings(settings_path)
    assert persisted.tile_selections == ["heart_rate", "workout_avg_power"]

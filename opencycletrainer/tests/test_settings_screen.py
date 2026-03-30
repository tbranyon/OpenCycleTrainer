from __future__ import annotations

import os
import shutil
import time
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication

from opencycletrainer.devices.mock_backend import MockDeviceBackend
from opencycletrainer.integrations.strava.sync_service import DuplicateUploadError
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
    screen.theme_mode_combo.setCurrentIndex(screen.theme_mode_combo.findData("dark"))

    all_tile_keys = [key for key, _ in TILE_OPTIONS]
    for key in all_tile_keys[: MAX_CONFIGURABLE_TILES + 1]:
        screen.set_tile_selected(key, True)

    screen.save_current_settings()
    persisted = load_settings(settings_path)

    assert persisted.ftp == 315
    assert persisted.lead_time == 7
    assert persisted.opentrueup_enabled is True
    assert persisted.theme_mode == "dark"
    assert len(persisted.tile_selections) == MAX_CONFIGURABLE_TILES
    assert all_tile_keys[MAX_CONFIGURABLE_TILES] not in persisted.tile_selections


def test_strava_section_shows_not_connected_by_default():
    _get_or_create_qapp()
    settings_path = _test_settings_path()
    save_settings(AppSettings(), settings_path)

    screen = SettingsScreen(settings_path=settings_path)

    assert "Not connected" in screen.strava_status_label.text()


def test_strava_auto_sync_checkbox_disabled_when_not_connected():
    _get_or_create_qapp()
    settings_path = _test_settings_path()
    save_settings(AppSettings(), settings_path)

    screen = SettingsScreen(settings_path=settings_path)

    assert not screen.strava_auto_sync_checkbox.isEnabled()


def test_strava_sync_now_button_disabled_when_not_connected():
    _get_or_create_qapp()
    settings_path = _test_settings_path()
    save_settings(AppSettings(), settings_path)

    screen = SettingsScreen(settings_path=settings_path)

    assert not screen.strava_sync_now_button.isEnabled()


def test_strava_auto_sync_checkbox_enabled_when_connected():
    _get_or_create_qapp()
    settings_path = _test_settings_path()
    save_settings(AppSettings(), settings_path)

    screen = SettingsScreen(settings_path=settings_path, strava_connected=True)

    assert screen.strava_auto_sync_checkbox.isEnabled()


def test_strava_sync_now_button_enabled_when_connected():
    _get_or_create_qapp()
    settings_path = _test_settings_path()
    save_settings(AppSettings(), settings_path)

    screen = SettingsScreen(settings_path=settings_path, strava_connected=True)

    assert screen.strava_sync_now_button.isEnabled()


def test_strava_auto_sync_persists_on_save():
    _get_or_create_qapp()
    settings_path = _test_settings_path()
    save_settings(AppSettings(), settings_path)

    screen = SettingsScreen(settings_path=settings_path, strava_connected=True)
    screen.strava_auto_sync_checkbox.setChecked(True)
    screen.save_current_settings()

    loaded = load_settings(settings_path)
    assert loaded.strava_auto_sync_enabled is True


def test_strava_status_shows_athlete_name_when_connected():
    _get_or_create_qapp()
    settings_path = _test_settings_path()
    save_settings(AppSettings(strava_athlete_name="Jane Smith"), settings_path)

    screen = SettingsScreen(settings_path=settings_path, strava_connected=True)

    assert "Jane Smith" in screen.strava_status_label.text()


def test_strava_connect_button_hidden_when_connected():
    _get_or_create_qapp()
    settings_path = _test_settings_path()
    save_settings(AppSettings(), settings_path)

    screen = SettingsScreen(settings_path=settings_path, strava_connected=True)

    # isHidden() reflects explicit show/hide state independently of whether the
    # parent window has been rendered (which it hasn't in headless tests).
    assert screen.strava_connect_button.isHidden()
    assert not screen.strava_disconnect_button.isHidden()


def test_strava_disconnect_updates_ui_to_not_connected():
    _get_or_create_qapp()
    settings_path = _test_settings_path()
    save_settings(AppSettings(strava_athlete_name="Jane Smith"), settings_path)

    screen = SettingsScreen(settings_path=settings_path, strava_connected=True)
    screen.disconnect_strava()

    assert "Not connected" in screen.strava_status_label.text()
    assert not screen.strava_connect_button.isHidden()
    assert screen.strava_disconnect_button.isHidden()
    assert not screen.strava_auto_sync_checkbox.isEnabled()
    assert not screen.strava_sync_now_button.isEnabled()


def test_strava_disconnect_clears_athlete_name_from_settings():
    _get_or_create_qapp()
    settings_path = _test_settings_path()
    save_settings(AppSettings(strava_athlete_name="Jane Smith"), settings_path)

    screen = SettingsScreen(settings_path=settings_path, strava_connected=True)
    screen.disconnect_strava()

    loaded = load_settings(settings_path)
    assert loaded.strava_athlete_name == ""


def test_main_window_applies_settings_screen_tile_updates_to_workout_screen():
    _get_or_create_qapp()
    settings_path = _test_settings_path()
    settings = AppSettings(tile_selections=["heart_rate"])
    save_settings(settings, settings_path)

    window = MainWindow(settings=settings, settings_path=settings_path, backend=MockDeviceBackend())
    assert window.workout_screen.get_selected_tile_keys() == ["heart_rate"]

    window.settings_screen.set_tile_selected("workout_avg_power", True)
    window.settings_screen.save_current_settings()

    assert window.workout_screen.get_selected_tile_keys() == ["heart_rate", "workout_avg_power"]
    persisted = load_settings(settings_path)
    assert persisted.tile_selections == ["heart_rate", "workout_avg_power"]


# ── Sync Now ──────────────────────────────────────────────────────────────────

def _wait_until(app: QApplication, predicate, timeout_seconds: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        app.processEvents()
        time.sleep(0.01)
    return predicate()


def test_sync_now_calls_upload_fn_with_selected_file(tmp_path: Path) -> None:
    app = _get_or_create_qapp()
    settings_path = _test_settings_path()
    save_settings(AppSettings(), settings_path)
    fit_file = tmp_path / "ride.fit"
    fit_file.write_bytes(b"FIT")

    uploaded: list[Path] = []
    screen = SettingsScreen(
        settings_path=settings_path,
        strava_connected=True,
        strava_sync_fn=lambda p: uploaded.append(p),
    )

    with patch(
        "opencycletrainer.ui.settings_screen.QFileDialog.getOpenFileName",
        return_value=(str(fit_file), "FIT Files (*.fit)"),
    ):
        screen._on_strava_sync_now()

    assert _wait_until(app, lambda: len(uploaded) == 1)
    assert uploaded[0] == fit_file


def test_sync_now_no_upload_when_no_file_selected(tmp_path: Path) -> None:
    app = _get_or_create_qapp()
    settings_path = _test_settings_path()
    save_settings(AppSettings(), settings_path)

    uploaded: list[Path] = []
    screen = SettingsScreen(
        settings_path=settings_path,
        strava_connected=True,
        strava_sync_fn=lambda p: uploaded.append(p),
    )

    with patch(
        "opencycletrainer.ui.settings_screen.QFileDialog.getOpenFileName",
        return_value=("", ""),
    ):
        screen._on_strava_sync_now()

    app.processEvents()
    assert uploaded == []


def test_sync_now_success_updates_status_label(tmp_path: Path) -> None:
    app = _get_or_create_qapp()
    settings_path = _test_settings_path()
    save_settings(AppSettings(), settings_path)
    fit_file = tmp_path / "ride.fit"
    fit_file.write_bytes(b"FIT")

    screen = SettingsScreen(
        settings_path=settings_path,
        strava_connected=True,
        strava_sync_fn=lambda _p: None,
    )

    with patch(
        "opencycletrainer.ui.settings_screen.QFileDialog.getOpenFileName",
        return_value=(str(fit_file), "FIT Files (*.fit)"),
    ):
        screen._on_strava_sync_now()

    assert _wait_until(app, lambda: "synced to Strava" in screen.status_label.text())


def test_sync_now_duplicate_updates_status_label(tmp_path: Path) -> None:
    app = _get_or_create_qapp()
    settings_path = _test_settings_path()
    save_settings(AppSettings(), settings_path)
    fit_file = tmp_path / "ride.fit"
    fit_file.write_bytes(b"FIT")

    def raises_duplicate(_p: Path) -> None:
        raise DuplicateUploadError("already uploaded")

    screen = SettingsScreen(
        settings_path=settings_path,
        strava_connected=True,
        strava_sync_fn=raises_duplicate,
    )

    with patch(
        "opencycletrainer.ui.settings_screen.QFileDialog.getOpenFileName",
        return_value=(str(fit_file), "FIT Files (*.fit)"),
    ):
        screen._on_strava_sync_now()

    assert _wait_until(app, lambda: "already synced" in screen.status_label.text())


def test_sync_now_failure_updates_status_label(tmp_path: Path) -> None:
    app = _get_or_create_qapp()
    settings_path = _test_settings_path()
    save_settings(AppSettings(), settings_path)
    fit_file = tmp_path / "ride.fit"
    fit_file.write_bytes(b"FIT")

    def raises_error(_p: Path) -> None:
        raise RuntimeError("network down")

    screen = SettingsScreen(
        settings_path=settings_path,
        strava_connected=True,
        strava_sync_fn=raises_error,
    )

    with patch(
        "opencycletrainer.ui.settings_screen.QFileDialog.getOpenFileName",
        return_value=(str(fit_file), "FIT Files (*.fit)"),
    ):
        screen._on_strava_sync_now()

    assert _wait_until(app, lambda: "sync failed" in screen.status_label.text())


# ── Auto-save ─────────────────────────────────────────────────────────────────

def test_spinbox_change_autosaves():
    _get_or_create_qapp()
    settings_path = _test_settings_path()
    save_settings(AppSettings(ftp=200), settings_path)

    screen = SettingsScreen(settings_path=settings_path)
    screen.ftp_spinbox.setValue(315)

    assert load_settings(settings_path).ftp == 315


def test_checkbox_change_autosaves():
    _get_or_create_qapp()
    settings_path = _test_settings_path()
    save_settings(AppSettings(opentrueup_enabled=False), settings_path)

    screen = SettingsScreen(settings_path=settings_path)
    screen.opentrueup_checkbox.setChecked(True)

    assert load_settings(settings_path).opentrueup_enabled is True


def test_theme_mode_change_autosaves():
    _get_or_create_qapp()
    settings_path = _test_settings_path()
    save_settings(AppSettings(theme_mode="system"), settings_path)

    screen = SettingsScreen(settings_path=settings_path)
    screen.theme_mode_combo.setCurrentIndex(screen.theme_mode_combo.findData("dark"))

    assert load_settings(settings_path).theme_mode == "dark"


def test_tile_checkbox_change_autosaves():
    _get_or_create_qapp()
    settings_path = _test_settings_path()
    save_settings(AppSettings(tile_selections=[]), settings_path)

    screen = SettingsScreen(settings_path=settings_path)
    screen.set_tile_selected("heart_rate", True)

    assert "heart_rate" in load_settings(settings_path).tile_selections


# ── OpenTrueUp availability ───────────────────────────────────────────────────

_OPENTRUEUP_TOOLTIP_FRAGMENT = "power meter"


def test_opentrueup_checkbox_disabled_by_default():
    """OpenTrueUp is unavailable when no paired devices are reported."""
    _get_or_create_qapp()
    settings_path = _test_settings_path()
    save_settings(AppSettings(), settings_path)

    screen = SettingsScreen(settings_path=settings_path)

    assert not screen.opentrueup_checkbox.isEnabled()


def test_opentrueup_checkbox_enabled_when_devices_available():
    _get_or_create_qapp()
    settings_path = _test_settings_path()
    save_settings(AppSettings(), settings_path)

    screen = SettingsScreen(settings_path=settings_path, opentrueup_devices_available=True)

    assert screen.opentrueup_checkbox.isEnabled()


def test_set_opentrueup_devices_available_enables_checkbox():
    _get_or_create_qapp()
    settings_path = _test_settings_path()
    save_settings(AppSettings(), settings_path)

    screen = SettingsScreen(settings_path=settings_path)
    screen.set_opentrueup_devices_available(True)

    assert screen.opentrueup_checkbox.isEnabled()


def test_set_opentrueup_devices_available_false_disables_checkbox():
    _get_or_create_qapp()
    settings_path = _test_settings_path()
    save_settings(AppSettings(), settings_path)

    screen = SettingsScreen(settings_path=settings_path, opentrueup_devices_available=True)
    screen.set_opentrueup_devices_available(False)

    assert not screen.opentrueup_checkbox.isEnabled()


def test_opentrueup_checkbox_has_tooltip():
    _get_or_create_qapp()
    settings_path = _test_settings_path()
    save_settings(AppSettings(), settings_path)

    screen = SettingsScreen(settings_path=settings_path)

    assert _OPENTRUEUP_TOOLTIP_FRAGMENT in screen.opentrueup_checkbox.toolTip().lower()


def test_opentrueup_label_has_tooltip():
    _get_or_create_qapp()
    settings_path = _test_settings_path()
    save_settings(AppSettings(), settings_path)

    screen = SettingsScreen(settings_path=settings_path)

    assert _OPENTRUEUP_TOOLTIP_FRAGMENT in screen.opentrueup_label.toolTip().lower()

def test_workout_data_dir_change_autosaves(tmp_path: Path):
    _get_or_create_qapp()
    settings_path = _test_settings_path()
    save_settings(AppSettings(workout_data_dir=None), settings_path)

    screen = SettingsScreen(settings_path=settings_path)
    screen.workout_data_dir_edit.setText(str(tmp_path))
    screen.workout_data_dir_edit.editingFinished.emit()

    assert load_settings(settings_path).workout_data_dir == tmp_path


# ── Show interval plot ────────────────────────────────────────────────────────


def test_show_interval_plot_checkbox_defaults_to_checked():
    _get_or_create_qapp()
    settings_path = _test_settings_path()
    save_settings(AppSettings(), settings_path)

    screen = SettingsScreen(settings_path=settings_path)

    assert screen.show_interval_plot_checkbox.isChecked()


def test_show_interval_plot_checkbox_reflects_saved_setting():
    _get_or_create_qapp()
    settings_path = _test_settings_path()
    save_settings(AppSettings(show_interval_plot=False), settings_path)

    screen = SettingsScreen(settings_path=settings_path)

    assert not screen.show_interval_plot_checkbox.isChecked()


def test_show_interval_plot_checkbox_autosaves():
    _get_or_create_qapp()
    settings_path = _test_settings_path()
    save_settings(AppSettings(show_interval_plot=True), settings_path)

    screen = SettingsScreen(settings_path=settings_path)
    screen.show_interval_plot_checkbox.setChecked(False)

    assert load_settings(settings_path).show_interval_plot is False


def test_sync_now_defaults_to_fit_subfolder_under_workout_data_dir(tmp_path: Path) -> None:
    _get_or_create_qapp()
    settings_path = _test_settings_path()
    save_settings(AppSettings(workout_data_dir=tmp_path), settings_path)

    screen = SettingsScreen(
        settings_path=settings_path,
        strava_connected=True,
        strava_sync_fn=lambda _p: None,
    )

    with patch(
        "opencycletrainer.ui.settings_screen.QFileDialog.getOpenFileName",
        return_value=("", ""),
    ) as picker:
        screen._on_strava_sync_now()

    assert picker.call_count == 1
    assert picker.call_args[0][2] == str(tmp_path / "FIT")

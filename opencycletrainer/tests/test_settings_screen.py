from __future__ import annotations

import os
import shutil
import time
from pathlib import Path
from unittest.mock import patch

import pytest

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


# ── Lead time increasing only ─────────────────────────────────────────────────


def test_lead_time_increasing_only_checkbox_defaults_to_checked():
    _get_or_create_qapp()
    settings_path = _test_settings_path()
    save_settings(AppSettings(), settings_path)

    screen = SettingsScreen(settings_path=settings_path)

    assert screen.lead_time_increasing_only_checkbox.isChecked()


def test_lead_time_increasing_only_checkbox_reflects_saved_setting():
    _get_or_create_qapp()
    settings_path = _test_settings_path()
    save_settings(AppSettings(lead_time_increasing_only=False), settings_path)

    screen = SettingsScreen(settings_path=settings_path)

    assert not screen.lead_time_increasing_only_checkbox.isChecked()


def test_lead_time_increasing_only_checkbox_autosaves():
    _get_or_create_qapp()
    settings_path = _test_settings_path()
    save_settings(AppSettings(lead_time_increasing_only=True), settings_path)

    screen = SettingsScreen(settings_path=settings_path)
    screen.lead_time_increasing_only_checkbox.setChecked(False)

    assert load_settings(settings_path).lead_time_increasing_only is False


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


# ── Version information ───────────────────────────────────────────────────────


def test_settings_screen_shows_version_label():
    from opencycletrainer import __version__

    _get_or_create_qapp()
    settings_path = _test_settings_path()
    save_settings(AppSettings(), settings_path)

    screen = SettingsScreen(settings_path=settings_path)

    assert __version__ in screen.version_label.text()


# ── FTP sync hooks ────────────────────────────────────────────────────────────


def _ftp_screen(**kwargs) -> tuple[SettingsScreen, Path]:
    _get_or_create_qapp()
    settings_path = _test_settings_path()
    save_settings(AppSettings(ftp=250), settings_path)
    return SettingsScreen(settings_path=settings_path, **kwargs), settings_path


def test_finishing_an_ftp_edit_is_announced_with_the_new_value():
    screen, _ = _ftp_screen(intervals_icu_api_key=None)
    edited: list[int] = []
    screen.ftp_edited.connect(edited.append)

    screen.ftp_spinbox.setValue(265)
    assert edited == []  # still typing: nothing announced yet
    screen.ftp_spinbox.editingFinished.emit()

    assert edited == [265]


def test_set_ftp_saves_and_applies_without_announcing_an_edit():
    screen, settings_path = _ftp_screen(intervals_icu_api_key=None)
    edited: list[int] = []
    applied: list[AppSettings] = []
    screen.ftp_edited.connect(edited.append)
    screen.settings_applied.connect(applied.append)

    screen.set_ftp(270)

    assert screen.ftp_spinbox.value() == 270
    assert load_settings(settings_path).ftp == 270
    assert applied[-1].ftp == 270
    assert edited == []


def test_declined_intervals_icu_ftp_is_saved_and_survives_other_edits():
    screen, settings_path = _ftp_screen(intervals_icu_api_key=None)

    screen.set_intervals_icu_declined_ftp(270)
    screen.lead_time_spinbox.setValue(9)

    assert load_settings(settings_path).intervals_icu_declined_ftp == 270


def test_api_key_is_offered_only_while_connected():
    connected, _ = _ftp_screen(intervals_icu_connected=True, intervals_icu_api_key="secret")
    assert connected.connected_intervals_icu_api_key() == "secret"

    connected.intervals_icu_api_key_edit.setText("half-typed replacement")
    assert connected.connected_intervals_icu_api_key() == "secret"

    with patch("opencycletrainer.ui.settings_screen.clear_api_key"):
        connected.disconnect_intervals_icu()
    assert connected.connected_intervals_icu_api_key() is None

    not_connected, _ = _ftp_screen(intervals_icu_connected=False, intervals_icu_api_key=None)
    assert not_connected.connected_intervals_icu_api_key() is None


def test_connecting_makes_the_validated_key_available():
    screen, _ = _ftp_screen(intervals_icu_connected=False, intervals_icu_api_key=None)
    screen.intervals_icu_api_key_edit.setText("fresh-key")

    with patch("opencycletrainer.ui.settings_screen.save_api_key"):
        screen._on_intervals_icu_connect_result("ok:Jane")

    assert screen.connected_intervals_icu_api_key() == "fresh-key"


# ── Grade simulation settings ─────────────────────────────────────────────────


def test_simulation_fields_reflect_saved_settings():
    _get_or_create_qapp()
    settings_path = _test_settings_path()
    save_settings(
        AppSettings(rider_weight_kg=68.5, bike_weight_kg=7.8, simulation_difficulty_percent=60),
        settings_path,
    )

    screen = SettingsScreen(settings_path=settings_path)

    assert screen.rider_weight_spinbox.value() == 68.5
    assert screen.bike_weight_spinbox.value() == 7.8
    assert screen.simulation_difficulty_spinbox.value() == 60


def test_simulation_fields_autosave():
    _get_or_create_qapp()
    settings_path = _test_settings_path()
    save_settings(AppSettings(), settings_path)
    screen = SettingsScreen(settings_path=settings_path)
    applied: list[AppSettings] = []
    screen.settings_applied.connect(applied.append)

    screen.rider_weight_spinbox.setValue(82.0)
    screen.bike_weight_spinbox.setValue(10.5)
    screen.simulation_difficulty_spinbox.setValue(75)

    loaded = load_settings(settings_path)
    assert loaded.rider_weight_kg == 82.0
    assert loaded.bike_weight_kg == 10.5
    assert loaded.simulation_difficulty_percent == 75
    assert applied[-1].total_mass_kg == 92.5


# ── Display units ─────────────────────────────────────────────────────────────


def test_imperial_units_toggle_defaults_to_off():
    _get_or_create_qapp()
    settings_path = _test_settings_path()
    save_settings(AppSettings(), settings_path)

    screen = SettingsScreen(settings_path=settings_path)

    assert not screen.imperial_units_checkbox.isChecked()


def test_imperial_units_toggle_reflects_saved_setting():
    _get_or_create_qapp()
    settings_path = _test_settings_path()
    save_settings(AppSettings(display_units="imperial"), settings_path)

    screen = SettingsScreen(settings_path=settings_path)

    assert screen.imperial_units_checkbox.isChecked()


def test_imperial_units_toggle_autosaves_and_notifies():
    _get_or_create_qapp()
    settings_path = _test_settings_path()
    save_settings(AppSettings(), settings_path)
    screen = SettingsScreen(settings_path=settings_path)
    applied: list[AppSettings] = []
    screen.settings_applied.connect(applied.append)

    screen.imperial_units_checkbox.setChecked(True)

    assert load_settings(settings_path).display_units == "imperial"
    assert applied[-1].display_units == "imperial"

    screen.imperial_units_checkbox.setChecked(False)

    assert load_settings(settings_path).display_units == "metric"


# ── Weights in the chosen units ───────────────────────────────────────────────

_KG_PER_LB = 0.45359237


def test_weights_are_shown_in_kilograms_for_metric_units():
    _get_or_create_qapp()
    settings_path = _test_settings_path()
    save_settings(AppSettings(rider_weight_kg=75.0, bike_weight_kg=9.0), settings_path)

    screen = SettingsScreen(settings_path=settings_path)

    assert screen.rider_weight_label.text() == "Rider Weight (kg)"
    assert screen.bike_weight_label.text() == "Bike Weight (kg)"
    assert screen.rider_weight_spinbox.value() == 75.0
    assert screen.bike_weight_spinbox.value() == 9.0


def test_weights_are_shown_in_pounds_for_imperial_units():
    _get_or_create_qapp()
    settings_path = _test_settings_path()
    save_settings(
        AppSettings(rider_weight_kg=75.0, bike_weight_kg=9.0, display_units="imperial"),
        settings_path,
    )

    screen = SettingsScreen(settings_path=settings_path)

    assert screen.rider_weight_label.text() == "Rider Weight (lb)"
    assert screen.bike_weight_label.text() == "Bike Weight (lb)"
    assert screen.rider_weight_spinbox.value() == 165.3
    assert screen.bike_weight_spinbox.value() == 19.8


def test_toggling_units_converts_the_weights_shown_without_changing_what_is_stored():
    _get_or_create_qapp()
    settings_path = _test_settings_path()
    save_settings(AppSettings(rider_weight_kg=68.4, bike_weight_kg=7.7), settings_path)
    screen = SettingsScreen(settings_path=settings_path)

    screen.imperial_units_checkbox.setChecked(True)

    assert screen.rider_weight_label.text() == "Rider Weight (lb)"
    assert screen.rider_weight_spinbox.value() == 150.8
    assert screen.bike_weight_spinbox.value() == 17.0
    loaded = load_settings(settings_path)
    assert loaded.rider_weight_kg == 68.4
    assert loaded.bike_weight_kg == 7.7

    screen.imperial_units_checkbox.setChecked(False)

    assert screen.rider_weight_label.text() == "Rider Weight (kg)"
    assert screen.rider_weight_spinbox.value() == 68.4
    assert screen.bike_weight_spinbox.value() == 7.7
    loaded = load_settings(settings_path)
    assert loaded.rider_weight_kg == 68.4
    assert loaded.bike_weight_kg == 7.7


def test_weights_entered_in_pounds_are_stored_in_kilograms():
    _get_or_create_qapp()
    settings_path = _test_settings_path()
    save_settings(AppSettings(display_units="imperial"), settings_path)
    screen = SettingsScreen(settings_path=settings_path)
    applied: list[AppSettings] = []
    screen.settings_applied.connect(applied.append)

    screen.rider_weight_spinbox.setValue(200.0)
    screen.bike_weight_spinbox.setValue(18.0)

    loaded = load_settings(settings_path)
    assert loaded.rider_weight_kg == pytest.approx(200.0 * _KG_PER_LB, abs=0.01)
    assert loaded.bike_weight_kg == pytest.approx(18.0 * _KG_PER_LB, abs=0.01)
    assert applied[-1].total_mass_kg == pytest.approx(218.0 * _KG_PER_LB, abs=0.02)


def test_a_weight_entered_in_pounds_survives_switching_to_metric():
    _get_or_create_qapp()
    settings_path = _test_settings_path()
    save_settings(AppSettings(display_units="imperial"), settings_path)
    screen = SettingsScreen(settings_path=settings_path)
    screen.rider_weight_spinbox.setValue(200.0)

    screen.imperial_units_checkbox.setChecked(False)

    assert screen.rider_weight_spinbox.value() == 90.7
    assert load_settings(settings_path).rider_weight_kg == pytest.approx(90.72, abs=0.01)

    screen.imperial_units_checkbox.setChecked(True)

    assert screen.rider_weight_spinbox.value() == 200.0


def test_weight_limits_follow_the_units():
    _get_or_create_qapp()
    settings_path = _test_settings_path()
    save_settings(AppSettings(), settings_path)
    screen = SettingsScreen(settings_path=settings_path)

    assert screen.rider_weight_spinbox.minimum() == 30.0
    assert screen.rider_weight_spinbox.maximum() == 200.0

    screen.imperial_units_checkbox.setChecked(True)

    assert screen.rider_weight_spinbox.minimum() * _KG_PER_LB == pytest.approx(30.0, abs=0.05)
    assert screen.rider_weight_spinbox.maximum() * _KG_PER_LB == pytest.approx(200.0, abs=0.05)
    assert screen.rider_weight_spinbox.minimum() * _KG_PER_LB >= 30.0
    assert screen.rider_weight_spinbox.maximum() * _KG_PER_LB <= 200.0
    assert screen.bike_weight_spinbox.maximum() * _KG_PER_LB <= 30.0


def test_heaviest_allowed_weight_in_pounds_is_not_clamped_on_reload():
    _get_or_create_qapp()
    settings_path = _test_settings_path()
    save_settings(AppSettings(display_units="imperial"), settings_path)
    screen = SettingsScreen(settings_path=settings_path)

    heaviest_lb = screen.rider_weight_spinbox.maximum()
    screen.rider_weight_spinbox.setValue(heaviest_lb)
    stored = load_settings(settings_path).rider_weight_kg

    reopened = SettingsScreen(settings_path=settings_path)

    assert heaviest_lb > 400.0
    assert stored == pytest.approx(heaviest_lb * _KG_PER_LB, abs=0.01)
    assert stored <= 200.0
    assert reopened.rider_weight_spinbox.value() == heaviest_lb


# ── Road surface ──────────────────────────────────────────────────────────────


def _surface_keys(screen: SettingsScreen) -> list[str]:
    combo = screen.road_surface_combo
    return [combo.itemData(index) for index in range(combo.count())]


def test_road_surface_dropdown_lists_every_surface_from_smooth_to_rough():
    _get_or_create_qapp()
    settings_path = _test_settings_path()
    save_settings(AppSettings(), settings_path)

    screen = SettingsScreen(settings_path=settings_path)

    assert _surface_keys(screen) == [
        "smooth_road",
        "aged_asphalt",
        "chipseal",
        "hardpack_gravel",
        "gravel",
        "loose_gravel",
    ]
    assert screen.road_surface_combo.currentData() == "smooth_road"
    assert screen.road_surface_combo.itemText(0) == "Smooth road"


def test_road_surface_dropdown_reflects_saved_setting():
    _get_or_create_qapp()
    settings_path = _test_settings_path()
    save_settings(AppSettings(road_surface="chipseal"), settings_path)

    screen = SettingsScreen(settings_path=settings_path)

    assert screen.road_surface_combo.currentData() == "chipseal"


def test_road_surface_dropdown_autosaves_and_notifies():
    _get_or_create_qapp()
    settings_path = _test_settings_path()
    save_settings(AppSettings(), settings_path)
    screen = SettingsScreen(settings_path=settings_path)
    applied: list[AppSettings] = []
    screen.settings_applied.connect(applied.append)

    screen.road_surface_combo.setCurrentIndex(screen.road_surface_combo.findData("gravel"))

    assert load_settings(settings_path).road_surface == "gravel"
    assert applied[-1].road_surface == "gravel"


# ── Course chart ──────────────────────────────────────────────────────────────


def test_course_zoom_span_reflects_saved_setting_and_autosaves():
    _get_or_create_qapp()
    settings_path = _test_settings_path()
    save_settings(AppSettings(course_zoom_span=2.0), settings_path)
    screen = SettingsScreen(settings_path=settings_path)

    assert screen.course_zoom_span_spinbox.value() == 2.0

    screen.course_zoom_span_spinbox.setValue(3.5)

    assert load_settings(settings_path).course_zoom_span == 3.5


def test_course_zoom_span_is_labelled_in_the_chosen_distance_unit():
    _get_or_create_qapp()
    settings_path = _test_settings_path()
    save_settings(AppSettings(), settings_path)
    screen = SettingsScreen(settings_path=settings_path)

    assert screen.course_zoom_span_label.text() == "Zoomed Course Span (km)"

    screen.imperial_units_checkbox.setChecked(True)

    assert screen.course_zoom_span_label.text() == "Zoomed Course Span (mi)"
    assert screen.course_zoom_span_spinbox.value() == 1.0


def test_course_grade_colors_toggle_reflects_saved_setting_and_autosaves():
    _get_or_create_qapp()
    settings_path = _test_settings_path()
    save_settings(AppSettings(course_grade_colors=True), settings_path)
    screen = SettingsScreen(settings_path=settings_path)

    assert screen.course_grade_colors_checkbox.isChecked()

    screen.course_grade_colors_checkbox.setChecked(False)

    assert load_settings(settings_path).course_grade_colors is False

from __future__ import annotations

import os
import shutil
from pathlib import Path
from datetime import datetime, timezone

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("PYQTGRAPH_QT_LIB", "PySide6")

from opencycletrainer.core.workout_library import WorkoutLibrary
from opencycletrainer.devices.mock_backend import MockDeviceBackend
from opencycletrainer.core.sensors import SensorSample
from opencycletrainer.devices.types import (
    CPS_MEASUREMENT_CHARACTERISTIC_UUID,
    FTMS_INDOOR_BIKE_DATA_CHARACTERISTIC_UUID,
)
from opencycletrainer.storage.settings import AppSettings, load_settings, save_settings
from opencycletrainer.ui.main_window import MainWindow
from opencycletrainer.ui.workout_library_screen import WorkoutLibraryScreen

_DATA_DIR = Path(__file__).parent / "data"
_STEP_MRC = _DATA_DIR / "step_only.mrc"


class _ShutdownSpy:
    """Minimal backend spy that records shutdown calls."""

    def __init__(self) -> None:
        self.shutdown_called = False

    def get_paired_devices(self) -> list:
        return []

    def get_available_devices(self) -> list:
        return []

    def shutdown(self) -> None:
        self.shutdown_called = True


def test_main_window_close_event_shuts_down_backend(qapp):
    window = MainWindow(backend=MockDeviceBackend())
    spy = _ShutdownSpy()
    window.devices_screen._backend = spy

    window.close()

    assert spy.shutdown_called


def _make_window(qapp) -> MainWindow:
    """Create a MainWindow after flushing any deferred Qt deletions from prior tests."""
    qapp.processEvents()
    return MainWindow(backend=MockDeviceBackend())


def _close_window(window, qapp) -> None:
    window.close()
    try:
        import shiboken6
        shiboken6.delete(window)
    except Exception:
        pass
    qapp.processEvents()


def test_main_window_has_library_tab(qapp):
    window = _make_window(qapp)
    try:
        tab_labels = [window.tabs.tabText(i) for i in range(window.tabs.count())]
        assert "Library" in tab_labels
    finally:
        _close_window(window, qapp)


def test_library_tab_is_between_workout_and_devices(qapp):
    window = _make_window(qapp)
    try:
        tab_labels = [window.tabs.tabText(i) for i in range(window.tabs.count())]
        workout_idx = tab_labels.index("Workout")
        library_idx = tab_labels.index("Library")
        devices_idx = tab_labels.index("Devices")
        assert workout_idx < library_idx < devices_idx
    finally:
        _close_window(window, qapp)


def test_load_from_library_button_navigates_to_library_tab(qapp):
    window = _make_window(qapp)
    try:
        window.tabs.setCurrentIndex(window._workout_tab_index)
        window.workout_screen.load_from_library_requested.emit()
        assert window.tabs.currentIndex() == window._library_tab_index
    finally:
        _close_window(window, qapp)


def test_library_workout_selected_loads_workout_and_navigates_to_workout_tab(qapp, tmp_path):
    user_dir = tmp_path / "user"
    user_dir.mkdir()
    shutil.copy2(_STEP_MRC, user_dir / _STEP_MRC.name)
    lib = WorkoutLibrary(user_dir=user_dir, prepackaged_dir=tmp_path / "empty")

    window = _make_window(qapp)
    try:
        window.workout_library_screen._library = lib
        window.tabs.setCurrentIndex(window._library_tab_index)
        window.workout_library_screen.workout_selected.emit(_STEP_MRC)
        assert window.tabs.currentIndex() == window._workout_tab_index
        assert window.workout_controller.last_snapshot is not None
    finally:
        _close_window(window, qapp)


def test_load_workout_public_method_loads_without_dialog(qapp):
    window = _make_window(qapp)
    try:
        window.workout_controller.load_workout(_STEP_MRC)
        assert window.workout_controller.last_snapshot is not None
        assert window.workout_screen.title_label.text() == "Step Session"
    finally:
        _close_window(window, qapp)


def test_tile_drag_reorder_persists_to_settings_file(qapp, tmp_path):
    settings_path = tmp_path / "settings.json"
    initial = AppSettings(tile_selections=["heart_rate", "cadence_rpm", "workout_avg_power"])
    save_settings(initial, settings_path)

    window = MainWindow(settings=initial, settings_path=settings_path, backend=MockDeviceBackend())
    try:
        window.workout_screen.reorder_tiles("heart_rate", "workout_avg_power")
        saved = load_settings(settings_path)
        assert saved.tile_selections == ["workout_avg_power", "cadence_rpm", "heart_rate"]
    finally:
        _close_window(window, qapp)


def test_tile_drag_reorder_updates_workout_screen_settings(qapp, tmp_path):
    settings_path = tmp_path / "settings.json"
    initial = AppSettings(tile_selections=["heart_rate", "cadence_rpm"])
    save_settings(initial, settings_path)

    window = MainWindow(settings=initial, settings_path=settings_path, backend=MockDeviceBackend())
    try:
        window.workout_screen.reorder_tiles("heart_rate", "cadence_rpm")
        assert window.workout_screen._settings.tile_selections == ["cadence_rpm", "heart_rate"]
    finally:
        _close_window(window, qapp)


def test_main_window_applies_dark_theme_to_chart_when_configured(qapp):
    window = _make_window(qapp)
    try:
        window._on_settings_applied(AppSettings(theme_mode="dark"))
        assert window.workout_screen.chart_widget._color_theme == "dark"
    finally:
        _close_window(window, qapp)


def test_main_window_applies_light_theme_to_chart_when_configured(qapp):
    window = _make_window(qapp)
    try:
        window._on_settings_applied(AppSettings(theme_mode="light"))
        assert window.workout_screen.chart_widget._color_theme == "light"
    finally:
        _close_window(window, qapp)


def test_main_window_routes_power_samples_by_characteristic_uuid(qapp):
    window = _make_window(qapp)
    trainer_values: list[int] = []
    bike_values: list[int] = []
    window.workout_controller.receive_power_watts = (
        lambda watts, now_monotonic=None: trainer_values.append(watts)
    )
    window.workout_controller.receive_bike_power_watts = (
        lambda watts, now_monotonic=None: bike_values.append(watts)
    )

    try:
        now = datetime(2026, 3, 11, 12, 0, 0, tzinfo=timezone.utc)
        window._on_sensor_sample(SensorSample(
            timestamp_utc=now,
            device_id="trainer-1",
            source_characteristic_uuid=FTMS_INDOOR_BIKE_DATA_CHARACTERISTIC_UUID,
            power_watts=180,
        ))
        window._on_sensor_sample(SensorSample(
            timestamp_utc=now,
            device_id="pm-1",
            source_characteristic_uuid=CPS_MEASUREMENT_CHARACTERISTIC_UUID,
            power_watts=220,
        ))

        assert trainer_values == [180]
        assert bike_values == [220]
    finally:
        _close_window(window, qapp)


def _ftp_window(tmp_path, monkeypatch, *, answer: bool) -> tuple[MainWindow, list]:
    """A main window connected to a fake intervals.icu that reports an FTP of 270 W."""
    from opencycletrainer.integrations.intervalsicu.ftp_service import RemoteFtp
    from opencycletrainer.ui import main_window as main_window_module

    monkeypatch.setattr(main_window_module, "get_api_key", lambda: "secret")
    monkeypatch.setattr(main_window_module, "get_tokens", lambda: None)
    settings_path = tmp_path / "settings.json"
    save_settings(AppSettings(ftp=250), settings_path)
    window = MainWindow(
        settings=load_settings(settings_path), settings_path=settings_path, backend=MockDeviceBackend(),
    )
    pushes: list = []
    sync = window.ftp_sync
    sync._fetch_fn = lambda api_key: RemoteFtp(watts=270, settings_id=22, indoor=False)
    sync._push_fn = lambda api_key, remote, watts: pushes.append((api_key, watts))
    sync._run_async = lambda job: job()
    sync._confirm = lambda title, text: answer
    return window, pushes


def test_startup_ftp_check_applies_the_intervals_icu_ftp_everywhere(qapp, tmp_path, monkeypatch):
    window, pushes = _ftp_window(tmp_path, monkeypatch, answer=True)
    try:
        window.check_intervals_icu_ftp()

        assert window.settings_screen.ftp_spinbox.value() == 270
        assert window._settings.ftp == 270
        assert load_settings(tmp_path / "settings.json").ftp == 270
        assert pushes == []
    finally:
        window.close()


def test_declining_the_startup_ftp_is_remembered_in_settings(qapp, tmp_path, monkeypatch):
    window, _ = _ftp_window(tmp_path, monkeypatch, answer=False)
    try:
        window.check_intervals_icu_ftp()

        saved = load_settings(tmp_path / "settings.json")
        assert (saved.ftp, saved.intervals_icu_declined_ftp) == (250, 270)
    finally:
        window.close()


def test_editing_ftp_in_settings_offers_to_update_intervals_icu(qapp, tmp_path, monkeypatch):
    window, pushes = _ftp_window(tmp_path, monkeypatch, answer=True)
    try:
        window.settings_screen.ftp_spinbox.setValue(265)
        window.settings_screen.ftp_spinbox.editingFinished.emit()

        assert pushes == [("secret", 265)]
    finally:
        window.close()


def test_main_window_forwards_monotonic_receipt_time_with_power(qapp):
    """Power readings reach the controller stamped with the BLE receipt time
    so the 1 s aggregator weights them by real arrival, not GUI-slot timing."""
    window = _make_window(qapp)
    trainer_calls: list[tuple[int, float | None]] = []
    bike_calls: list[tuple[int, float | None]] = []
    window.workout_controller.receive_power_watts = (
        lambda watts, now_monotonic=None: trainer_calls.append((watts, now_monotonic))
    )
    window.workout_controller.receive_bike_power_watts = (
        lambda watts, now_monotonic=None: bike_calls.append((watts, now_monotonic))
    )

    try:
        now = datetime(2026, 3, 11, 12, 0, 0, tzinfo=timezone.utc)
        window._on_sensor_sample(SensorSample(
            timestamp_utc=now,
            device_id="trainer-1",
            source_characteristic_uuid=FTMS_INDOOR_BIKE_DATA_CHARACTERISTIC_UUID,
            power_watts=180,
            received_at_monotonic=42.25,
        ))
        window._on_sensor_sample(SensorSample(
            timestamp_utc=now,
            device_id="pm-1",
            source_characteristic_uuid=CPS_MEASUREMENT_CHARACTERISTIC_UUID,
            power_watts=220,
            received_at_monotonic=43.5,
        ))
        assert trainer_calls == [(180, 42.25)]
        assert bike_calls == [(220, 43.5)]
    finally:
        _close_window(window, qapp)


def test_closing_the_window_saves_a_ride_image_still_waiting_for_map_tiles(qapp, tmp_path):
    from opencycletrainer.core.course_model import Course, CoursePoint

    course = Course(
        name="Map Course",
        points=tuple(
            CoursePoint(
                distance_m=100.0 * i, elevation_m=100.0, latitude_deg=45.0 + 0.001 * i, longitude_deg=7.0,
            )
            for i in range(5)
        ),
    )
    window = MainWindow(
        settings=AppSettings(), settings_path=tmp_path / "settings.json", backend=MockDeviceBackend(),
    )
    window.workout_screen.load_course_chart(course)
    path = window.workout_screen.export_chart_image(tmp_path / "ride.png", "Course")
    assert not path.exists()  # no test map tile ever arrives

    _close_window(window, qapp)

    assert path.is_file()


def test_closing_the_window_remembers_the_course_map_layout(qapp, tmp_path):
    settings_path = tmp_path / "settings.json"
    save_settings(AppSettings(), settings_path)
    window = MainWindow(settings=AppSettings(), settings_path=settings_path, backend=MockDeviceBackend())
    window.workout_screen.course_map_panel.set_collapsed(True)

    _close_window(window, qapp)

    saved = load_settings(settings_path)
    assert saved.course_map_collapsed is True
    assert saved.course_map_width_px is None

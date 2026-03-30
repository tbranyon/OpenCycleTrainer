from __future__ import annotations

import os
import shutil
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("PYQTGRAPH_QT_LIB", "PySide6")

from opencycletrainer.core.workout_library import WorkoutLibrary
from opencycletrainer.devices.mock_backend import MockDeviceBackend
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

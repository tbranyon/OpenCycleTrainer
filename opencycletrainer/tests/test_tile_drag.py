from __future__ import annotations

import os

from PySide6.QtWidgets import QApplication, QLabel

from opencycletrainer.storage.settings import AppSettings
from opencycletrainer.ui.workout_screen import MetricTile, WorkoutScreen


def _get_or_create_qapp() -> QApplication:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


# --- MetricTile ---


def test_metric_tile_stores_key():
    _get_or_create_qapp()
    tile = MetricTile(title="Heart Rate", key="heart_rate")
    assert tile.key == "heart_rate"


def test_metric_tile_has_drag_requested_signal():
    _get_or_create_qapp()
    tile = MetricTile(title="Heart Rate", key="heart_rate")
    emitted = []
    tile.drag_requested.connect(emitted.append)
    # Signal is connectable and emittable
    tile.drag_requested.emit("heart_rate")
    assert emitted == ["heart_rate"]


def test_metric_tile_drag_not_active_on_init():
    _get_or_create_qapp()
    tile = MetricTile(title="Heart Rate", key="heart_rate")
    assert tile._drag_start_pos is None


# --- WorkoutScreen drag state ---


def test_workout_screen_has_tile_order_changed_signal():
    _get_or_create_qapp()
    screen = WorkoutScreen(settings=AppSettings(tile_selections=["heart_rate", "cadence_rpm"]))
    emitted = []
    screen.tile_order_changed.connect(emitted.append)
    screen.tile_order_changed.emit(["cadence_rpm", "heart_rate"])
    assert emitted == [["cadence_rpm", "heart_rate"]]


def test_workout_screen_no_drag_in_progress_on_init():
    _get_or_create_qapp()
    screen = WorkoutScreen(settings=AppSettings(tile_selections=["heart_rate", "cadence_rpm"]))
    assert screen._drag_source_key is None
    assert screen._drag_ghost is None
    assert screen._drag_target_key is None


# --- reorder_tiles ---


def test_reorder_tiles_swaps_positions():
    _get_or_create_qapp()
    screen = WorkoutScreen(
        settings=AppSettings(tile_selections=["heart_rate", "cadence_rpm", "workout_avg_power"])
    )
    screen.reorder_tiles("heart_rate", "workout_avg_power")
    assert screen.get_selected_tile_keys() == ["workout_avg_power", "cadence_rpm", "heart_rate"]


def test_reorder_tiles_adjacent():
    _get_or_create_qapp()
    screen = WorkoutScreen(
        settings=AppSettings(tile_selections=["heart_rate", "cadence_rpm"])
    )
    screen.reorder_tiles("heart_rate", "cadence_rpm")
    assert screen.get_selected_tile_keys() == ["cadence_rpm", "heart_rate"]


def test_reorder_tiles_emits_tile_order_changed():
    _get_or_create_qapp()
    screen = WorkoutScreen(
        settings=AppSettings(tile_selections=["heart_rate", "cadence_rpm"])
    )
    emitted = []
    screen.tile_order_changed.connect(emitted.append)
    screen.reorder_tiles("heart_rate", "cadence_rpm")
    assert emitted == [["cadence_rpm", "heart_rate"]]


def test_reorder_tiles_noop_when_same_key():
    _get_or_create_qapp()
    screen = WorkoutScreen(
        settings=AppSettings(tile_selections=["heart_rate", "cadence_rpm"])
    )
    emitted = []
    screen.tile_order_changed.connect(emitted.append)
    screen.reorder_tiles("heart_rate", "heart_rate")
    assert emitted == []
    assert screen.get_selected_tile_keys() == ["heart_rate", "cadence_rpm"]


def test_reorder_tiles_noop_when_key_not_present():
    _get_or_create_qapp()
    screen = WorkoutScreen(
        settings=AppSettings(tile_selections=["heart_rate", "cadence_rpm"])
    )
    emitted = []
    screen.tile_order_changed.connect(emitted.append)
    screen.reorder_tiles("heart_rate", "workout_avg_power")  # workout_avg_power not selected
    assert emitted == []
    assert screen.get_selected_tile_keys() == ["heart_rate", "cadence_rpm"]


def test_reorder_tiles_rebuilds_tile_widgets():
    _get_or_create_qapp()
    screen = WorkoutScreen(
        settings=AppSettings(tile_selections=["heart_rate", "cadence_rpm"])
    )
    tile_before = screen._tile_by_key.get("cadence_rpm")
    screen.reorder_tiles("heart_rate", "cadence_rpm")
    tile_after = screen._tile_by_key.get("cadence_rpm")
    # Tiles are recreated on reorder
    assert tile_after is not tile_before


# --- Ghost widget lifecycle ---


def test_on_drag_started_creates_ghost():
    _get_or_create_qapp()
    screen = WorkoutScreen(
        settings=AppSettings(tile_selections=["heart_rate", "cadence_rpm"])
    )
    screen._on_drag_started("heart_rate")
    assert screen._drag_ghost is not None


def test_on_drag_started_sets_source_key():
    _get_or_create_qapp()
    screen = WorkoutScreen(
        settings=AppSettings(tile_selections=["heart_rate", "cadence_rpm"])
    )
    screen._on_drag_started("heart_rate")
    assert screen._drag_source_key == "heart_rate"


def test_complete_drag_removes_ghost():
    _get_or_create_qapp()
    screen = WorkoutScreen(
        settings=AppSettings(tile_selections=["heart_rate", "cadence_rpm"])
    )
    screen._on_drag_started("heart_rate")
    screen._complete_drag(None)
    assert screen._drag_ghost is None


def test_complete_drag_clears_source_key():
    _get_or_create_qapp()
    screen = WorkoutScreen(
        settings=AppSettings(tile_selections=["heart_rate", "cadence_rpm"])
    )
    screen._on_drag_started("heart_rate")
    screen._complete_drag(None)
    assert screen._drag_source_key is None


def test_complete_drag_with_target_reorders_tiles():
    _get_or_create_qapp()
    screen = WorkoutScreen(
        settings=AppSettings(tile_selections=["heart_rate", "cadence_rpm"])
    )
    screen._on_drag_started("heart_rate")
    screen._drag_target_key = "cadence_rpm"
    screen._complete_drag("cadence_rpm")
    assert screen.get_selected_tile_keys() == ["cadence_rpm", "heart_rate"]


def test_complete_drag_no_target_leaves_order_unchanged():
    _get_or_create_qapp()
    screen = WorkoutScreen(
        settings=AppSettings(tile_selections=["heart_rate", "cadence_rpm"])
    )
    screen._on_drag_started("heart_rate")
    screen._complete_drag(None)
    assert screen.get_selected_tile_keys() == ["heart_rate", "cadence_rpm"]


def test_ghost_is_label_child_of_screen():
    _get_or_create_qapp()
    screen = WorkoutScreen(
        settings=AppSettings(tile_selections=["heart_rate", "cadence_rpm"])
    )
    screen._on_drag_started("heart_rate")
    assert isinstance(screen._drag_ghost, QLabel)
    assert screen._drag_ghost.parent() is screen

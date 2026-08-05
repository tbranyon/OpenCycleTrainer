from __future__ import annotations

import os

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from opencycletrainer.core.dfa.pipeline import DFA_WINDOW_SECONDS, DfaRecord, SignalQuality
from opencycletrainer.storage.settings import AppSettings, THEME_MODE_DARK, THEME_MODE_LIGHT
from opencycletrainer.ui.theme import resolve_status_color
from opencycletrainer.ui.tile_config import TILE_LABEL_BY_KEY
from opencycletrainer.ui.workout_screen import DfaMetricTile, WorkoutScreen


def _get_or_create_qapp() -> QApplication:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _make_record(**overrides) -> DfaRecord:
    defaults = dict(
        t=1.0,
        alpha1=0.81,
        mean_power_w=215.0,
        hr_bpm=142.0,
        rmssd_ms=42.0,
        quality=SignalQuality.GOOD,
        artifact_fraction=0.0,
        artifact_breakdown={"missed": 0, "extra": 0, "ectopic": 0, "long": 0, "short": 0},
        max_correction_run=0,
        r2_loglog=0.98,
        quality_reason="",
    )
    defaults.update(overrides)
    return DfaRecord(**defaults)


def _press(tile, pos: QPoint) -> None:
    event = QMouseEvent(QEvent.MouseButtonPress, QPointF(pos), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    tile.mousePressEvent(event)


def _move(tile, pos: QPoint) -> None:
    event = QMouseEvent(QEvent.MouseMove, QPointF(pos), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    tile.mouseMoveEvent(event)


def _release(tile, pos: QPoint) -> None:
    event = QMouseEvent(QEvent.MouseButtonRelease, QPointF(pos), Qt.LeftButton, Qt.NoButton, Qt.NoModifier)
    tile.mouseReleaseEvent(event)


# --- Registration ---


def test_dfa_a1_registered_in_tile_options():
    assert TILE_LABEL_BY_KEY.get("dfa_a1") == "DFA α1"


# --- Click vs drag ---


def test_subthreshold_click_toggles_popup_open_then_closed():
    _get_or_create_qapp()
    tile = DfaMetricTile(title="DFA α1", key="dfa_a1")
    tile.set_dfa_record(_make_record())

    _press(tile, QPoint(5, 5))
    _release(tile, QPoint(5, 5))
    assert tile._is_open is True

    _press(tile, QPoint(5, 5))
    _release(tile, QPoint(5, 5))
    assert tile._is_open is False


def test_drag_past_threshold_emits_drag_requested_and_does_not_open_popup():
    _get_or_create_qapp()
    tile = DfaMetricTile(title="DFA α1", key="dfa_a1")
    tile.set_dfa_record(_make_record())

    emitted = []
    tile.drag_requested.connect(emitted.append)

    _press(tile, QPoint(5, 5))
    _move(tile, QPoint(20, 5))  # delta of 15px, past the 6px threshold
    _release(tile, QPoint(20, 5))

    assert emitted == ["dfa_a1"]
    assert tile._is_open is False


# --- Quality dot colour ---


def test_quality_dot_colour_changes_across_signal_qualities():
    _get_or_create_qapp()
    tile = DfaMetricTile(title="DFA α1", key="dfa_a1")

    role_by_quality = {
        SignalQuality.GOOD: "success",
        SignalQuality.DEGRADED: "warning",
        SignalQuality.POOR: "danger",
        SignalQuality.INSUFFICIENT: "muted",
    }
    colors = {}
    for quality, role in role_by_quality.items():
        tile.set_dfa_record(_make_record(quality=quality))
        expected_color = resolve_status_color(role, THEME_MODE_LIGHT)
        assert expected_color in tile.quality_dot.styleSheet()
        colors[quality] = expected_color

    assert len(set(colors.values())) == 4


def test_quality_dot_colour_follows_theme_mode():
    _get_or_create_qapp()
    tile = DfaMetricTile(title="DFA α1", key="dfa_a1")
    tile.set_dfa_record(_make_record(quality=SignalQuality.GOOD))
    assert resolve_status_color("success", THEME_MODE_LIGHT) in tile.quality_dot.styleSheet()

    tile.apply_color_theme(THEME_MODE_DARK)
    assert resolve_status_color("success", THEME_MODE_DARK) in tile.quality_dot.styleSheet()


# --- Popup row formatting ---


def test_popup_rows_for_populated_record():
    _get_or_create_qapp()
    tile = DfaMetricTile(title="DFA α1", key="dfa_a1")
    record = _make_record(
        mean_power_w=215.0,
        r2_loglog=0.98,
        rmssd_ms=42.0,
        artifact_fraction=0.012,
        artifact_breakdown={"missed": 2, "extra": 0, "ectopic": 1, "long": 0, "short": 0},
        quality_reason="",
    )
    tile.set_dfa_record(record)
    tile._open_popup()
    popup = tile._popup

    assert popup.power_row.text() == f"Window power   215 W  ({DFA_WINDOW_SECONDS} s)"
    assert popup.r2_row.text() == "Scaling fit (R²)   0.98"
    assert popup.rmssd_row.text() == "RMSSD   42 ms"
    assert popup.artifact_row.text() == "Artifacts   1.2%  (2 missed, 1 ectopic)"
    assert popup.reason_row.isVisible() is False


def test_popup_rows_for_missing_power_and_visible_reason():
    _get_or_create_qapp()
    tile = DfaMetricTile(title="DFA α1", key="dfa_a1")
    record = _make_record(
        alpha1=None,
        mean_power_w=None,
        rmssd_ms=None,
        quality=SignalQuality.POOR,
        artifact_fraction=0.08,
        artifact_breakdown={"missed": 0, "extra": 0, "ectopic": 0, "long": 0, "short": 0},
        quality_reason="High artifact rate (8% corrected beats)",
    )
    tile.set_dfa_record(record)
    tile._open_popup()
    popup = tile._popup

    assert popup.power_row.text() == f"Window power   -- W  ({DFA_WINDOW_SECONDS} s)"
    assert popup.rmssd_row.text() == "RMSSD   -- ms"
    assert popup.artifact_row.text() == "Artifacts   8.0%  (none)"
    assert popup.reason_row.text() == "High artifact rate (8% corrected beats)"
    assert popup.reason_row.isVisible() is True


# --- WorkoutScreen wiring ---


def test_workout_screen_creates_dfa_metric_tile_when_selected():
    _get_or_create_qapp()
    screen = WorkoutScreen(settings=AppSettings(tile_selections=["dfa_a1"]))
    tile = screen._tile_by_key.get("dfa_a1")
    assert isinstance(tile, DfaMetricTile)


def test_workout_screen_set_dfa_record_routes_to_tile():
    _get_or_create_qapp()
    screen = WorkoutScreen(settings=AppSettings(tile_selections=["dfa_a1"]))
    record = _make_record(mean_power_w=180.0)
    screen.set_dfa_record(record)
    tile = screen._tile_by_key["dfa_a1"]
    assert tile.power_label.text() == "180 W"


def test_workout_screen_set_dfa_record_noop_when_tile_not_selected():
    _get_or_create_qapp()
    screen = WorkoutScreen(settings=AppSettings(tile_selections=["heart_rate"]))
    screen.set_dfa_record(_make_record())  # must not raise


# --- Chart overlay gating (spec [0e]: the tile selection is the feature switch) ---


def test_chart_alpha1_overlay_enabled_when_tile_selected_at_construction():
    _get_or_create_qapp()
    screen = WorkoutScreen(settings=AppSettings(tile_selections=["dfa_a1"]))
    assert screen.chart_widget._dfa_alpha1_enabled is True


def test_chart_alpha1_overlay_disabled_when_tile_not_selected():
    _get_or_create_qapp()
    screen = WorkoutScreen(settings=AppSettings(tile_selections=["heart_rate"]))
    assert screen.chart_widget._dfa_alpha1_enabled is False


def test_apply_settings_toggles_chart_alpha1_overlay():
    _get_or_create_qapp()
    screen = WorkoutScreen(settings=AppSettings(tile_selections=["heart_rate"]))
    screen.apply_settings(AppSettings(tile_selections=["dfa_a1"]))
    assert screen.chart_widget._dfa_alpha1_enabled is True
    screen.apply_settings(AppSettings(tile_selections=["heart_rate"]))
    assert screen.chart_widget._dfa_alpha1_enabled is False


def test_screen_update_charts_forwards_alpha1_series_to_widget():
    _get_or_create_qapp()
    screen = WorkoutScreen(settings=AppSettings(tile_selections=["dfa_a1"]))
    captured = {}

    def _capture(elapsed, interval_index, power_series, hr_series, alpha1_series=None):
        captured["alpha1_series"] = alpha1_series

    screen.chart_widget.update_charts = _capture
    screen.update_charts(5.0, 0, [], [], [(3.0, 0.82)])
    assert captured["alpha1_series"] == [(3.0, 0.82)]

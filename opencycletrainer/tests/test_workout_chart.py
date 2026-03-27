from __future__ import annotations

import os

import numpy as np
import pytest

from opencycletrainer.core.workout_model import Workout, WorkoutInterval


def _qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _flat_workout(ftp: int = 200) -> Workout:
    """Two flat intervals: 5 min warmup at 50 %, 10 min at 90 %."""
    return Workout(
        name="Test Flat",
        ftp_watts=ftp,
        intervals=(
            WorkoutInterval(
                start_offset_seconds=0,
                duration_seconds=300,
                start_percent_ftp=50.0,
                end_percent_ftp=50.0,
                start_target_watts=100,
                end_target_watts=100,
            ),
            WorkoutInterval(
                start_offset_seconds=300,
                duration_seconds=600,
                start_percent_ftp=90.0,
                end_percent_ftp=90.0,
                start_target_watts=180,
                end_target_watts=180,
            ),
        ),
    )


def _ramp_workout(ftp: int = 200) -> Workout:
    """Single ramp interval from 100 W to 200 W over 10 minutes."""
    return Workout(
        name="Test Ramp",
        ftp_watts=ftp,
        intervals=(
            WorkoutInterval(
                start_offset_seconds=0,
                duration_seconds=600,
                start_percent_ftp=50.0,
                end_percent_ftp=100.0,
                start_target_watts=100,
                end_target_watts=200,
            ),
        ),
    )


# ── _build_target_series ──────────────────────────────────────────────────────

def test_build_target_series_flat_step():
    from opencycletrainer.ui.workout_chart import _build_target_series

    workout = _flat_workout()
    t, w = _build_target_series(workout)

    # Two intervals × 2 points each = 4 points total
    assert len(t) == 4
    assert len(w) == 4

    # First interval: starts at t=0, 100 W; ends at t=300, 100 W (flat)
    assert t[0] == pytest.approx(0.0)
    assert w[0] == pytest.approx(100.0)
    assert t[1] == pytest.approx(300.0)
    assert w[1] == pytest.approx(100.0)

    # Second interval: starts at t=300, 180 W; ends at t=900, 180 W (flat)
    # Boundary at t=300 creates the step: w[1]=100 -> w[2]=180
    assert t[2] == pytest.approx(300.0)
    assert w[2] == pytest.approx(180.0)
    assert t[3] == pytest.approx(900.0)
    assert w[3] == pytest.approx(180.0)


def test_build_target_series_ramp():
    from opencycletrainer.ui.workout_chart import _build_target_series

    workout = _ramp_workout()
    t, w = _build_target_series(workout)

    assert len(t) == 2
    assert t[0] == pytest.approx(0.0)
    assert w[0] == pytest.approx(100.0)
    assert t[1] == pytest.approx(600.0)
    assert w[1] == pytest.approx(200.0)


# ── _compute_y_max ────────────────────────────────────────────────────────────

def test_compute_y_max_rounds_up_to_next_50():
    from opencycletrainer.ui.workout_chart import _compute_y_max

    workout = _flat_workout(ftp=200)
    # target_peak=180, ftp=200 → raw = 200 * 1.10 = 220 → rounded up = 250
    y_max = _compute_y_max(workout, 200)
    assert y_max == pytest.approx(250.0)


def test_compute_y_max_uses_target_peak_when_above_ftp():
    from opencycletrainer.ui.workout_chart import _compute_y_max

    workout = Workout(
        name="Hard",
        ftp_watts=200,
        intervals=(
            WorkoutInterval(
                start_offset_seconds=0,
                duration_seconds=300,
                start_percent_ftp=150.0,
                end_percent_ftp=150.0,
                start_target_watts=300,
                end_target_watts=300,
            ),
        ),
    )
    # target_peak=300, ftp=200 → raw = 300 * 1.10 = 330 → rounded up = 350
    y_max = _compute_y_max(workout, 200)
    assert y_max == pytest.approx(350.0)


# ── _TimeAxisItem ─────────────────────────────────────────────────────────────

def test_time_axis_tick_count_near_8():
    _qapp()
    from opencycletrainer.ui.workout_chart import _TimeAxisItem

    axis = _TimeAxisItem("bottom")
    # 3600 s span → raw = 3600/7 ≈ 514 → rounded to 515... actually round(514/5)*5
    # round(102.8)*5 = 103*5 = 515. 3600/515 ≈ 6.99 → 7 intervals = 8 ticks (0..7)
    levels = axis.tickValues(0.0, 3600.0, 800.0)
    assert len(levels) == 1
    _, ticks = levels[0]
    # Should be approximately 8 ticks
    assert 7 <= len(ticks) <= 9


def test_time_axis_tick_starts_at_minval():
    _qapp()
    from opencycletrainer.ui.workout_chart import _TimeAxisItem

    axis = _TimeAxisItem("bottom")
    levels = axis.tickValues(570.0, 1770.0, 800.0)
    _, ticks = levels[0]
    assert ticks[0] == pytest.approx(570.0)


def test_time_axis_tick_spacing_rounds_to_nearest_5():
    _qapp()
    from opencycletrainer.ui.workout_chart import _TimeAxisItem

    axis = _TimeAxisItem("bottom")
    # span = 700; raw = 100; rounds to 100 (which is a multiple of 5)
    levels = axis.tickValues(0.0, 700.0, 800.0)
    spacing, _ = levels[0]
    assert spacing % 5 == 0


def test_time_axis_tick_strings_format():
    _qapp()
    from opencycletrainer.ui.workout_chart import _TimeAxisItem

    axis = _TimeAxisItem("bottom")
    labels = axis.tickStrings([0, 60, 90, 3661], 1.0, 60.0)
    assert labels[0] == "00:00"
    assert labels[1] == "01:00"
    assert labels[2] == "01:30"
    assert labels[3] == "61:01"


# ── WorkoutChartWidget (widget integration) ───────────────────────────────────

def test_widget_loads_workout_and_sets_target_series():
    _qapp()
    from opencycletrainer.ui.workout_chart import WorkoutChartWidget

    widget = WorkoutChartWidget()
    workout = _flat_workout()
    widget.load_workout(workout, ftp_watts=200)

    # Target series should have 4 points (2 intervals × 2 boundary points)
    x, y = widget._workout_target.getData()
    assert len(x) == 4
    assert len(y) == 4


def test_widget_update_charts_grows_live_series():
    _qapp()
    from opencycletrainer.ui.workout_chart import WorkoutChartWidget

    widget = WorkoutChartWidget()
    workout = _flat_workout()
    widget.load_workout(workout, ftp_watts=200)

    power = [(float(i), 180) for i in range(10)]
    hr    = [(float(i), 140) for i in range(10)]

    widget.update_charts(10.0, 0, power, hr)

    x, _ = widget._workout_actual.getData()
    assert len(x) == 10


def test_widget_position_indicator_value():
    _qapp()
    from opencycletrainer.ui.workout_chart import WorkoutChartWidget

    widget = WorkoutChartWidget()
    widget.load_workout(_flat_workout(), ftp_watts=200)
    widget.update_charts(123.0, 0, [], [])

    assert widget._interval_pos.value() == pytest.approx(123.0)
    assert widget._workout_pos.value()  == pytest.approx(123.0)


def test_widget_interval_range_shifts_on_index_change():
    _qapp()
    from opencycletrainer.ui.workout_chart import WorkoutChartWidget

    widget = WorkoutChartWidget()
    workout = _flat_workout()
    widget.load_workout(workout, ftp_watts=200)

    # After load: interval 0 window is [max(0, 0-30), min(900, 300+30)] = [0, 330]
    x_min_0, x_max_0 = widget._interval_plot.getViewBox().viewRange()[0]
    assert x_min_0 == pytest.approx(0.0)
    assert x_max_0 == pytest.approx(330.0)

    # Move to interval 1: [max(0, 300-30), min(900, 900+30)] = [270, 900]
    widget.update_charts(350.0, 1, [], [])
    x_min_1, x_max_1 = widget._interval_plot.getViewBox().viewRange()[0]
    assert x_min_1 == pytest.approx(270.0)
    assert x_max_1 == pytest.approx(900.0)


def test_widget_pre_interval_defaults_to_first():
    """current_interval_index=None should show the first interval window."""
    _qapp()
    from opencycletrainer.ui.workout_chart import WorkoutChartWidget

    widget = WorkoutChartWidget()
    workout = _flat_workout()
    widget.load_workout(workout, ftp_watts=200)

    # Manually reset to something else, then call update with None
    widget.update_charts(0.0, None, [], [])

    x_min, _ = widget._interval_plot.getViewBox().viewRange()[0]
    # Should show interval 0 window: x_min = 0
    assert x_min == pytest.approx(0.0)


def test_widget_clear_empties_all_series():
    _qapp()
    from opencycletrainer.ui.workout_chart import WorkoutChartWidget

    widget = WorkoutChartWidget()
    widget.load_workout(_flat_workout(), ftp_watts=200)
    widget.update_charts(60.0, 0, [(float(i), 150) for i in range(10)], [])
    widget.clear()

    for item in (
        widget._workout_target, widget._workout_actual, widget._workout_hr,
        widget._interval_target, widget._interval_actual, widget._interval_hr,
    ):
        x, _ = item.getData()
        assert x is None or len(x) == 0


def test_widget_ftp_line_position():
    _qapp()
    from opencycletrainer.ui.workout_chart import WorkoutChartWidget

    widget = WorkoutChartWidget()
    widget.load_workout(_flat_workout(), ftp_watts=250)

    assert widget._workout_ftp_line.value()  == pytest.approx(250.0)
    assert widget._interval_ftp_line.value() == pytest.approx(250.0)


def test_add_skip_marker_appends_regions():
    _qapp()
    from opencycletrainer.ui.workout_chart import WorkoutChartWidget

    widget = WorkoutChartWidget()
    widget.load_workout(_flat_workout(), ftp_watts=200)

    assert len(widget._skip_markers) == 0

    widget.add_skip_marker(100.0, 300.0)
    assert len(widget._skip_markers) == 1
    interval_region, workout_region = widget._skip_markers[0]
    lo, hi = interval_region.getRegion()
    assert lo == pytest.approx(100.0)
    assert hi == pytest.approx(300.0)

    widget.add_skip_marker(400.0, 450.0)
    assert len(widget._skip_markers) == 2


def test_load_workout_clears_skip_markers():
    _qapp()
    from opencycletrainer.ui.workout_chart import WorkoutChartWidget

    widget = WorkoutChartWidget()
    widget.load_workout(_flat_workout(), ftp_watts=200)
    widget.add_skip_marker(100.0, 200.0)
    assert len(widget._skip_markers) == 1

    widget.load_workout(_flat_workout(), ftp_watts=200)
    assert len(widget._skip_markers) == 0


def test_clear_removes_skip_markers():
    _qapp()
    from opencycletrainer.ui.workout_chart import WorkoutChartWidget

    widget = WorkoutChartWidget()
    widget.load_workout(_flat_workout(), ftp_watts=200)
    widget.add_skip_marker(50.0, 150.0)
    widget.add_skip_marker(200.0, 300.0)
    assert len(widget._skip_markers) == 2

    widget.clear()
    assert len(widget._skip_markers) == 0


def test_widget_apply_color_theme_switches_between_light_and_dark():
    _qapp()
    from opencycletrainer.ui.workout_chart import WorkoutChartWidget

    widget = WorkoutChartWidget()
    widget.apply_color_theme("dark")
    assert widget._color_theme == "dark"

    widget.apply_color_theme("light")
    assert widget._color_theme == "light"

"""Tests for NiceGUI ECharts workout chart — Phase 4."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from opencycletrainer.core.workout_model import Workout, WorkoutInterval
from opencycletrainer.ui.workout_chart_ng import (
    WorkoutEChartsManager,
    _get_series,
    build_target_data,
    compute_y_max,
    interval_xrange,
    make_chart_options,
)

# ── Fixture helpers ────────────────────────────────────────────────────────────


def _iv(start: int, duration: int, start_w: int, end_w: int) -> WorkoutInterval:
    ftp = 200
    return WorkoutInterval(
        start_offset_seconds=start,
        duration_seconds=duration,
        start_percent_ftp=start_w / ftp * 100,
        end_percent_ftp=end_w / ftp * 100,
        start_target_watts=start_w,
        end_target_watts=end_w,
    )


def _workout(*intervals: WorkoutInterval) -> Workout:
    return Workout(name="Test", ftp_watts=200, intervals=tuple(intervals))


class _MockEChart:
    """Minimal mock for ``ui.echart``."""

    def __init__(self, options: dict) -> None:
        self.options = options
        self.update_calls = 0

    def update(self) -> None:
        self.update_calls += 1


# ── build_target_data ─────────────────────────────────────────────────────────


def test_build_target_data_empty():
    w = _workout()
    assert build_target_data(w) == []


def test_build_target_data_flat_interval():
    w = _workout(_iv(0, 600, 200, 200))
    data = build_target_data(w)
    assert data == [[0.0, 200.0], [600.0, 200.0]]


def test_build_target_data_ramp_interval():
    w = _workout(_iv(0, 300, 100, 200))
    data = build_target_data(w)
    assert data == [[0.0, 100.0], [300.0, 200.0]]


def test_build_target_data_multiple_intervals():
    w = _workout(_iv(0, 600, 150, 150), _iv(600, 300, 250, 250))
    data = build_target_data(w)
    assert data == [
        [0.0, 150.0], [600.0, 150.0],
        [600.0, 250.0], [900.0, 250.0],
    ]


def test_build_target_data_uses_offset_not_duration():
    """start_offset_seconds, not duration, must be used for x coordinates."""
    iv = _iv(120, 180, 200, 200)   # starts at 120, ends at 300
    w = _workout(iv)
    data = build_target_data(w)
    assert data[0][0] == 120.0
    assert data[1][0] == 300.0


# ── compute_y_max ─────────────────────────────────────────────────────────────


def test_compute_y_max_target_dominates():
    w = _workout(_iv(0, 600, 300, 300))   # peak 300 W, ftp 200
    y = compute_y_max(w, 200)
    # raw = max(300, 200) * 1.10 = 330 → ceil to next 50 = 350
    assert y == 350.0


def test_compute_y_max_ftp_dominates():
    w = _workout(_iv(0, 600, 100, 100))   # peak 100 W, ftp 250
    y = compute_y_max(w, 250)
    # raw = max(100, 250) * 1.10 = 275 → next 50 = 300
    assert y == 300.0


def test_compute_y_max_rounds_to_step():
    w = _workout(_iv(0, 600, 200, 200))
    y = compute_y_max(w, 200)
    assert y % 50 == 0


def test_compute_y_max_empty_workout():
    w = _workout()
    y = compute_y_max(w, 200)
    # raw = 200 * 1.10 = 220 → next 50 = 250
    assert y == 250.0


# ── interval_xrange ───────────────────────────────────────────────────────────


def test_interval_xrange_first_interval():
    w = _workout(_iv(0, 600, 200, 200), _iv(600, 300, 200, 200))
    x_min, x_max = interval_xrange(w, 0)
    # interval 0: start=0, end=600; padded: max(0, 0-30)=0, min(900, 600+30)=630
    assert x_min == 0.0
    assert x_max == 630.0


def test_interval_xrange_middle_interval():
    # Three intervals: 0-300, 300-600, 600-900
    w = _workout(
        _iv(0, 300, 200, 200),
        _iv(300, 300, 200, 200),
        _iv(600, 300, 200, 200),
    )
    x_min, x_max = interval_xrange(w, 1)
    # interval 1: start=300, end=600; padded: 270, 630
    assert x_min == 270.0
    assert x_max == 630.0


def test_interval_xrange_clamps_low():
    w = _workout(_iv(0, 600, 200, 200))
    x_min, _ = interval_xrange(w, 0)
    assert x_min >= 0.0


def test_interval_xrange_clamps_high():
    w = _workout(_iv(0, 600, 200, 200))
    _, x_max = interval_xrange(w, 0)
    assert x_max <= float(w.total_duration_seconds)


def test_interval_xrange_index_clamped():
    w = _workout(_iv(0, 600, 200, 200))
    # index beyond last should not crash
    x_min, x_max = interval_xrange(w, 999)
    assert x_min >= 0.0
    assert x_max <= float(w.total_duration_seconds)


def test_interval_xrange_empty_workout():
    w = _workout()
    x_min, x_max = interval_xrange(w, 0)
    assert x_min == 0.0
    assert x_max == 0.0


# ── make_chart_options ────────────────────────────────────────────────────────


def test_make_chart_options_has_five_series():
    opts = make_chart_options(400.0, 3600.0)
    assert len(opts['series']) == 5


def test_make_chart_options_series_ids():
    opts = make_chart_options(400.0, 3600.0)
    ids = {s['id'] for s in opts['series']}
    assert ids == {'target', 'actual', 'hr', 'ftp', 'cursor'}


def test_make_chart_options_returns_fresh_dict():
    opts1 = make_chart_options(400.0, 3600.0)
    opts2 = make_chart_options(400.0, 3600.0)
    assert opts1 is not opts2
    opts1['series'][0]['data'].append([0, 0])
    assert opts2['series'][0]['data'] == []


def test_make_chart_options_y_max_and_x_max():
    opts = make_chart_options(350.0, 1800.0)
    assert opts['yAxis']['max'] == 350.0
    assert opts['xAxis']['max'] == 1800.0


# ── _get_series ───────────────────────────────────────────────────────────────


def test_get_series_found():
    opts = make_chart_options(400.0, 3600.0)
    s = _get_series(opts, 'actual')
    assert s['id'] == 'actual'


def test_get_series_not_found():
    opts = make_chart_options(400.0, 3600.0)
    with pytest.raises(KeyError):
        _get_series(opts, 'nonexistent')


# ── WorkoutEChartsManager ────────────────────────────────────────────────────


def _make_manager() -> tuple[WorkoutEChartsManager, _MockEChart, _MockEChart]:
    iv_opts = make_chart_options(400.0, 3600.0)
    ov_opts = make_chart_options(400.0, 3600.0)
    iv_chart = _MockEChart(iv_opts)
    ov_chart = _MockEChart(ov_opts)
    mgr = WorkoutEChartsManager(iv_chart, ov_chart)  # type: ignore[arg-type]
    return mgr, iv_chart, ov_chart


def test_manager_load_workout_sets_target_data():
    mgr, iv, ov = _make_manager()
    w = _workout(_iv(0, 600, 200, 200))
    mgr.load_workout(w, 200)

    expected = [[0.0, 200.0], [600.0, 200.0]]
    assert _get_series(ov.options, 'target')['data'] == expected
    assert _get_series(iv.options, 'target')['data'] == expected


def test_manager_load_workout_sets_ftp_line():
    mgr, iv, ov = _make_manager()
    w = _workout(_iv(0, 600, 200, 200))
    mgr.load_workout(w, 250)

    ftp_ov = _get_series(ov.options, 'ftp')['data']
    assert ftp_ov[0][1] == 250.0
    assert ftp_ov[1][1] == 250.0


def test_manager_load_workout_clears_skip_markers():
    mgr, iv, ov = _make_manager()
    w = _workout(_iv(0, 600, 200, 200))
    mgr.load_workout(w, 200)
    mgr.add_skip_marker(100.0, 200.0)

    # reload — skip markers must be cleared
    mgr.load_workout(w, 200)
    assert _get_series(ov.options, 'target')['markArea']['data'] == []
    assert _get_series(iv.options, 'target')['markArea']['data'] == []


def test_manager_load_workout_triggers_update():
    mgr, iv, ov = _make_manager()
    w = _workout(_iv(0, 600, 200, 200))
    mgr.load_workout(w, 200)
    assert iv.update_calls == 1
    assert ov.update_calls == 1


def test_manager_update_charts_no_workout_is_noop():
    mgr, iv, ov = _make_manager()
    mgr.update_charts(10.0, 0, [(5.0, 200)], [])
    assert iv.update_calls == 0
    assert ov.update_calls == 0


def test_manager_update_charts_pushes_power_to_overview():
    mgr, iv, ov = _make_manager()
    w = _workout(_iv(0, 3600, 200, 200))
    mgr.load_workout(w, 200)
    iv.update_calls = ov.update_calls = 0

    mgr.update_charts(60.0, 0, [(30.0, 210), (60.0, 215)], [])
    assert _get_series(ov.options, 'actual')['data'] == [
        [30.0, 210.0], [60.0, 215.0]
    ]


def test_manager_update_charts_slices_power_to_interval():
    mgr, iv, ov = _make_manager()
    # interval: 0-600, context: 0-630
    w = _workout(_iv(0, 600, 200, 200), _iv(600, 600, 200, 200))
    mgr.load_workout(w, 200)
    iv.update_calls = ov.update_calls = 0

    # elapsed=700, in second interval; x range = 570..1230
    power = [(100.0, 200), (650.0, 210), (800.0, 205)]
    mgr.update_charts(700.0, 1, power, [])

    iv_actual = _get_series(iv.options, 'actual')['data']
    # only the 650 and 800 s samples are in [570, 1230]
    times = [pt[0] for pt in iv_actual]
    assert 650.0 in times
    assert 800.0 in times
    assert 100.0 not in times


def test_manager_update_charts_cursor_position():
    mgr, iv, ov = _make_manager()
    w = _workout(_iv(0, 3600, 200, 200))
    mgr.load_workout(w, 200)

    mgr.update_charts(123.0, 0, [], [])
    cursor_ov = _get_series(ov.options, 'cursor')['data']
    assert cursor_ov[0][0] == 123.0
    assert cursor_ov[1][0] == 123.0


def test_manager_add_skip_marker_appears_on_both_charts():
    mgr, iv, ov = _make_manager()
    w = _workout(_iv(0, 3600, 200, 200))
    mgr.load_workout(w, 200)

    mgr.add_skip_marker(300.0, 600.0)

    iv_areas = _get_series(iv.options, 'target')['markArea']['data']
    ov_areas = _get_series(ov.options, 'target')['markArea']['data']
    assert len(iv_areas) == 1
    assert len(ov_areas) == 1
    assert iv_areas[0] == [{'xAxis': 300.0}, {'xAxis': 600.0}]


def test_manager_skip_markers_accumulate():
    mgr, iv, ov = _make_manager()
    w = _workout(_iv(0, 3600, 200, 200))
    mgr.load_workout(w, 200)

    mgr.add_skip_marker(100.0, 200.0)
    mgr.add_skip_marker(500.0, 700.0)

    areas = _get_series(ov.options, 'target')['markArea']['data']
    assert len(areas) == 2


def test_manager_update_triggers_both_updates():
    mgr, iv, ov = _make_manager()
    w = _workout(_iv(0, 3600, 200, 200))
    mgr.load_workout(w, 200)
    iv.update_calls = ov.update_calls = 0

    mgr.update_charts(60.0, 0, [], [])
    assert iv.update_calls == 1
    assert ov.update_calls == 1


def test_manager_interval_xrange_updates_on_index_change():
    mgr, iv, ov = _make_manager()
    # two equal intervals
    w = _workout(_iv(0, 600, 200, 200), _iv(600, 600, 200, 200))
    mgr.load_workout(w, 200)

    mgr.update_charts(700.0, 1, [], [])
    # interval 1: start=600, end=1200; padded min=570, max=1200
    assert iv.options['xAxis']['min'] == 570.0
    assert iv.options['xAxis']['max'] == 1200.0

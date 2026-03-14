"""NiceGUI ECharts-based workout charts — Phase 4.

Two stacked ECharts instances:
  • interval view  — current interval ± 30 s context
  • overview       — full workout duration
"""
from __future__ import annotations

import copy

from nicegui import ui

from opencycletrainer.core.workout_model import Workout

# ── Chart colour palette (matches design system tokens) ───────────────────────

_C_TARGET_LINE = '#3b82f6'
_C_TARGET_FILL = 'rgba(59,130,246,0.20)'
_C_ACTUAL       = '#22c55e'
_C_HR           = '#ef4444'
_C_FTP          = '#56566a'
_C_CURSOR       = 'rgba(200,200,200,0.70)'
_C_SKIP         = 'rgba(234,179,8,0.30)'
_C_AXIS         = '#2c2c3c'
_C_LABEL        = '#8e8ea8'
_C_GRID         = '#21212d'

_Y_STEP    = 50.0   # W between y-axis grid lines
_CONTEXT_S = 30     # s of padding on each side of the interval view

# JS formatter: seconds → MM:SS
_TIME_FMT = (
    'function(val){'
    'var m=Math.floor(val/60);'
    'var s=String(Math.floor(val%60)).padStart(2,"0");'
    'return m+":"+s;'
    '}'
)


# ── Pure computation helpers ──────────────────────────────────────────────────

def build_target_data(workout: Workout) -> list[list[float]]:
    """Build target-power series as ``[[t_seconds, watts], ...]``.

    Each interval contributes two points (start and end) so flat intervals
    render as horizontal bars and ramps render as sloped lines.
    """
    data: list[list[float]] = []
    for iv in workout.intervals:
        data.append([float(iv.start_offset_seconds), float(iv.start_target_watts)])
        data.append([float(iv.end_offset_seconds),   float(iv.end_target_watts)])
    return data


def compute_y_max(workout: Workout, ftp_watts: int) -> float:
    """Return y-axis ceiling rounded up to the next 50 W step."""
    if workout.intervals:
        peak = float(max(
            max(iv.start_target_watts, iv.end_target_watts)
            for iv in workout.intervals
        ))
    else:
        peak = float(ftp_watts)
    raw = max(peak, float(ftp_watts)) * 1.10
    return float((int(raw / _Y_STEP) + 1) * _Y_STEP)


def interval_xrange(workout: Workout, interval_index: int) -> tuple[float, float]:
    """Return (x_min, x_max) in seconds for the interval view.

    Adds *_CONTEXT_S* padding on each side and clamps to [0, total_duration].
    """
    intervals = workout.intervals
    if not intervals:
        return (0.0, float(workout.total_duration_seconds))
    idx = max(0, min(interval_index, len(intervals) - 1))
    iv    = intervals[idx]
    total = float(workout.total_duration_seconds)
    return (
        max(0.0, float(iv.start_offset_seconds) - _CONTEXT_S),
        min(total, float(iv.end_offset_seconds)  + _CONTEXT_S),
    )


def make_chart_options(y_max: float, x_max: float) -> dict:
    """Return a complete ECharts options dict with empty data series.

    Call once per chart and pass the result to ``ui.echart()``.  The
    returned dict is fresh on every call so each chart gets its own copy.
    """
    return {
        'animation': False,
        'backgroundColor': 'transparent',
        'grid': {
            'left':         '44px',
            'right':        '16px',
            'top':          '8px',
            'bottom':       '28px',
            'containLabel': False,
        },
        'xAxis': {
            'type': 'value',
            'min':  0,
            'max':  x_max,
            'axisLabel': {
                'color':     _C_LABEL,
                'formatter': _TIME_FMT,
                'fontSize':  11,
            },
            'splitLine': {'show': False},
            'axisLine': {'lineStyle': {'color': _C_AXIS}},
            'axisTick': {'lineStyle': {'color': _C_AXIS}},
        },
        'yAxis': {
            'type': 'value',
            'min':  0,
            'max':  y_max,
            'splitLine': {'lineStyle': {'color': _C_GRID, 'type': 'dashed'}},
            'axisLabel': {
                'color':     _C_LABEL,
                'formatter': '{value}',
                'fontSize':  11,
            },
            'axisLine': {'show': False},
            'axisTick': {'show': False},
        },
        'series': [
            {   # 0 — target power (filled area)
                'id':          'target',
                'type':        'line',
                'data':        [],
                'lineStyle':   {'color': _C_TARGET_LINE, 'width': 2},
                'areaStyle':   {'color': _C_TARGET_FILL, 'origin': 'start'},
                'itemStyle':   {'color': _C_TARGET_LINE},
                'showSymbol':  False,
                'markArea': {
                    'silent':    True,
                    'itemStyle': {'color': _C_SKIP},
                    'data':      [],
                },
            },
            {   # 1 — actual power line
                'id':          'actual',
                'type':        'line',
                'data':        [],
                'lineStyle':   {'color': _C_ACTUAL, 'width': 2},
                'itemStyle':   {'color': _C_ACTUAL},
                'showSymbol':  False,
                'connectNulls': False,
            },
            {   # 2 — heart rate line
                'id':          'hr',
                'type':        'line',
                'data':        [],
                'lineStyle':   {'color': _C_HR, 'width': 1.5},
                'itemStyle':   {'color': _C_HR},
                'showSymbol':  False,
                'connectNulls': False,
            },
            {   # 3 — FTP reference (dashed horizontal)
                'id':          'ftp',
                'type':        'line',
                'data':        [],
                'lineStyle':   {'color': _C_FTP, 'type': 'dashed', 'width': 1},
                'itemStyle':   {'color': _C_FTP},
                'showSymbol':  False,
                'silent':      True,
            },
            {   # 4 — position cursor (vertical line at current elapsed)
                'id':          'cursor',
                'type':        'line',
                'data':        [],
                'lineStyle':   {'color': _C_CURSOR, 'width': 1},
                'showSymbol':  False,
                'silent':      True,
            },
        ],
    }


def _get_series(options: dict, series_id: str) -> dict:
    """Return the series dict matching *series_id* inside *options*."""
    for s in options.get('series', []):
        if s.get('id') == series_id:
            return s
    raise KeyError(f'Series {series_id!r} not found in chart options')


# ── Manager class ─────────────────────────────────────────────────────────────

class WorkoutEChartsManager:
    """Owns two ``ui.echart`` instances and drives all live chart updates."""

    def __init__(
        self,
        interval_chart: ui.echart,
        overview_chart: ui.echart,
    ) -> None:
        self._interval = interval_chart
        self._overview = overview_chart
        self._workout:    Workout | None = None
        self._ftp:        int            = 200
        self._y_max:      float          = 400.0
        self._skip_areas: list           = []

    # ── Public API ────────────────────────────────────────────────────────────

    def load_workout(self, workout: Workout, ftp_watts: int) -> None:
        """Initialise both charts with the target trace for *workout*."""
        self._workout    = workout
        self._ftp        = max(1, int(ftp_watts))
        self._y_max      = compute_y_max(workout, self._ftp)
        self._skip_areas = []

        target_data  = build_target_data(workout)
        total        = float(workout.total_duration_seconds)
        ftp_data: list[list[float]] = [
            [0.0,   float(self._ftp)],
            [total, float(self._ftp)],
        ]
        init_cursor: list[list[float]] = [[0.0, 0.0], [0.0, self._y_max]]
        x_iv_min, x_iv_max = interval_xrange(workout, 0)

        for chart, x_min, x_max in (
            (self._overview, 0.0,      total),
            (self._interval, x_iv_min, x_iv_max),
        ):
            opts = chart.options
            opts['xAxis']['min'] = x_min
            opts['xAxis']['max'] = x_max
            opts['yAxis']['max'] = self._y_max
            _get_series(opts, 'target')['data']                 = target_data
            _get_series(opts, 'target')['markArea']['data']     = []
            _get_series(opts, 'actual')['data']                 = []
            _get_series(opts, 'hr')['data']                     = []
            _get_series(opts, 'ftp')['data']                    = ftp_data
            _get_series(opts, 'cursor')['data']                 = copy.copy(init_cursor)
            chart.update()

    def update_charts(
        self,
        elapsed: float,
        interval_index: int | None,
        power_series: list[tuple[float, int]],
        hr_series: list[tuple[float, int]],
    ) -> None:
        """Push live traces and cursor to both charts. Called at ~1 Hz."""
        if self._workout is None:
            return

        power_data: list[list[float]] = [[t, float(w)]   for t, w   in power_series]
        hr_data:    list[list[float]] = [[t, float(bpm)] for t, bpm in hr_series]
        cursor:     list[list[float]] = [
            [float(elapsed), 0.0],
            [float(elapsed), self._y_max],
        ]

        # Overview — full series, fixed x range
        ov = self._overview.options
        _get_series(ov, 'actual')['data'] = power_data
        _get_series(ov, 'hr')['data']     = hr_data
        _get_series(ov, 'cursor')['data'] = cursor
        self._overview.update()

        # Interval — windowed x range + sliced data
        idx    = interval_index if interval_index is not None else 0
        x_min, x_max = interval_xrange(self._workout, idx)
        iv_opts = self._interval.options
        iv_opts['xAxis']['min'] = x_min
        iv_opts['xAxis']['max'] = x_max
        _get_series(iv_opts, 'actual')['data'] = [
            [t, float(w)]   for t, w   in power_series if x_min <= t <= x_max
        ]
        _get_series(iv_opts, 'hr')['data'] = [
            [t, float(bpm)] for t, bpm in hr_series    if x_min <= t <= x_max
        ]
        _get_series(iv_opts, 'cursor')['data'] = cursor
        self._interval.update()

    def add_skip_marker(self, elapsed_before: float, elapsed_after: float) -> None:
        """Add a yellow shaded skip region to both charts."""
        self._skip_areas.append(
            [{'xAxis': elapsed_before}, {'xAxis': elapsed_after}]
        )
        mark_data = list(self._skip_areas)
        for chart in (self._interval, self._overview):
            _get_series(chart.options, 'target')['markArea']['data'] = mark_data
            chart.update()

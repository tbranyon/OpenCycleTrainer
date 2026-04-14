from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("PYQTGRAPH_QT_LIB", "PySide6")

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QVBoxLayout, QWidget

from opencycletrainer.core.workout_model import Workout

# ── Colour palette ────────────────────────────────────────────────────────────
_TARGET_PEN   = (59,  130, 246)           # #3b82f6 blue
_TARGET_FILL  = (59,  130, 246, 64)       # light blue ~25 % alpha
_ACTUAL_PEN   = (34,  197, 94)            # #22c55e green
_HR_PEN       = (239, 68,  68)            # #ef4444 red
_POS_PEN      = (200, 200, 200, 180)      # light grey, slim
_FTP_LINE_PEN = (150, 150, 150, 128)      # muted grey, dashed
_FTP_TEXT_COL = (150, 150, 150)
_SKIP_BRUSH   = (234, 179,   8,  80)      # yellow ~30 % alpha
_AXIS_TEXT_LIGHT = (71, 85, 105)
_AXIS_TEXT_DARK = (203, 213, 225)
_PLOT_BACKGROUND_LIGHT = (255, 255, 255)
_PLOT_BACKGROUND_DARK = (15, 23, 42)
_POS_PEN_DARK = (148, 163, 184, 190)
_FTP_LINE_PEN_DARK = (148, 163, 184, 170)
_FTP_TEXT_COL_DARK = (148, 163, 184)
_GRID_ALPHA_LIGHT = 0.2
_GRID_ALPHA_DARK = 0.35
_COLOR_THEME_LIGHT = "light"
_COLOR_THEME_DARK = "dark"

_Y_STEP = 50.0          # watts between horizontal grid lines
_CONTEXT_SECONDS = 30   # padding on each side of interval chart

# Chart export dimensions — 16:9 is widely used by Strava and social platforms.
_EXPORT_WIDTH  = 1920
_EXPORT_HEIGHT = 1080
_5_MIN_SECONDS = 300.0  # five minutes in seconds


# ── Time axis ─────────────────────────────────────────────────────────────────

class _TimeAxisItem(pg.AxisItem):
    """Bottom axis that formats seconds as MM:SS with ~8 ticks across the span.

    For spans where ticks would be >= 2.5 minutes apart, snaps to 5-minute
    boundaries (05:00, 10:00, …).  For shorter spans (interval view) it snaps
    to the nearest 5-second increment instead.
    """

    def tickValues(self, minVal: float, maxVal: float, size: float) -> list:
        span = maxVal - minVal
        if span < 1:
            return []
        raw = span / 7.0
        if raw >= _5_MIN_SECONDS / 2:
            # Large span: snap to 5-minute multiples
            spacing = max(_5_MIN_SECONDS, round(raw / _5_MIN_SECONDS) * _5_MIN_SECONDS)
        else:
            # Short span (interval view): snap to nearest 5 s, minimum 5 s
            spacing = max(5.0, round(raw / 5.0) * 5.0)
        ticks: list[float] = []
        t = minVal
        while t <= maxVal + 1e-6:
            ticks.append(t)
            t += spacing
        return [(spacing, ticks)]

    def tickStrings(self, values: list, scale: float, spacing: float) -> list[str]:
        result = []
        for v in values:
            s = max(0, int(round(v)))
            result.append(f"{s // 60:02d}:{s % 60:02d}")
        return result


# ── Main widget ───────────────────────────────────────────────────────────────

class WorkoutChartWidget(QWidget):
    """
    Two stacked live charts:
      • top  — interval view: current interval ± 30 s context
      • bottom — workout overview: full workout duration
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self._workout: Workout | None = None
        self._interval_durations: list[int] = []
        self._ftp_watts: int = 200
        self._free_ride_mode: bool = False
        self._free_ride_x_window_seconds: int = 1800
        self._color_theme: str = _COLOR_THEME_LIGHT

        self._interval_plot = _make_plot()
        self._workout_plot  = _make_plot()

        layout.addWidget(self._interval_plot, 6)  # ~60 % of height
        layout.addWidget(self._workout_plot,  4)  # ~40 %

        # ── series items ──────────────────────────────────────────────
        self._interval_target = _make_target_item()
        self._interval_actual = _make_actual_item()
        self._interval_hr     = _make_hr_item()
        self._interval_pos    = _make_position_line()
        self._interval_ftp_line = _make_ftp_line()
        self._interval_ftp_text = _make_ftp_text()

        self._workout_target  = _make_target_item()
        self._workout_actual  = _make_actual_item()
        self._workout_hr      = _make_hr_item()
        self._workout_pos     = _make_position_line()
        self._workout_ftp_line = _make_ftp_line()
        self._workout_ftp_text = _make_ftp_text()

        self._skip_markers: list[tuple[pg.LinearRegionItem, pg.LinearRegionItem]] = []

        for item in (
            self._interval_target, self._interval_actual, self._interval_hr,
            self._interval_ftp_line, self._interval_ftp_text, self._interval_pos,
        ):
            self._interval_plot.addItem(item)

        for item in (
            self._workout_target, self._workout_actual, self._workout_hr,
            self._workout_ftp_line, self._workout_ftp_text, self._workout_pos,
        ):
            self._workout_plot.addItem(item)

        # Reposition FTP text label whenever x range changes
        self._interval_plot.getViewBox().sigXRangeChanged.connect(
            lambda _vb, _r: self._reposition_ftp_text(
                self._interval_plot, self._interval_ftp_text,
            ),
        )
        self._workout_plot.getViewBox().sigXRangeChanged.connect(
            lambda _vb, _r: self._reposition_ftp_text(
                self._workout_plot, self._workout_ftp_text,
            ),
        )
        self.apply_color_theme(_COLOR_THEME_LIGHT)

    # ── Public API ────────────────────────────────────────────────────────────

    def load_workout(self, workout: Workout, ftp_watts: int) -> None:
        """Render the static target trace and reset live series."""
        self._workout   = workout
        self._ftp_watts = max(1, int(ftp_watts))
        self._interval_durations = [iv.duration_seconds for iv in workout.intervals]

        t, w = build_target_series(workout)
        self._interval_target.setData(t, w)
        self._workout_target.setData(t, w)

        y_max = compute_y_max(workout, self._ftp_watts)
        for plot in (self._interval_plot, self._workout_plot):
            _configure_y_axis(plot, y_max)

        for ftp_line in (self._interval_ftp_line, self._workout_ftp_line):
            ftp_line.setValue(float(self._ftp_watts))
        for ftp_text in (self._interval_ftp_text, self._workout_ftp_text):
            ftp_text.setText("FTP")

        total = float(workout.total_duration_seconds)
        self._workout_plot.setXRange(0.0, total, padding=0)
        self._reposition_ftp_text(self._workout_plot, self._workout_ftp_text)

        self._update_interval_range(0)

        for item in (
            self._interval_actual, self._interval_hr,
            self._workout_actual,  self._workout_hr,
        ):
            item.setData([], [])

        for pos in (self._interval_pos, self._workout_pos):
            pos.setValue(0.0)

        self._clear_skip_markers()

    def add_skip_marker(self, elapsed_before: float, elapsed_after: float) -> None:
        """Add a yellow shaded region spanning the skipped interval on both charts."""
        interval_region = pg.LinearRegionItem(
            values=[elapsed_before, elapsed_after],
            orientation="vertical",
            brush=pg.mkBrush(_SKIP_BRUSH),
            movable=False,
        )
        workout_region = pg.LinearRegionItem(
            values=[elapsed_before, elapsed_after],
            orientation="vertical",
            brush=pg.mkBrush(_SKIP_BRUSH),
            movable=False,
        )
        self._interval_plot.addItem(interval_region)
        self._workout_plot.addItem(workout_region)
        self._skip_markers.append((interval_region, workout_region))

    def rebuild_target_series(self, interval_durations: list[int]) -> None:
        """Rebuild the target trace after interval durations change (e.g. extend).

        Updates both chart items and expands the workout overview X range to the
        new total duration.
        """
        if self._workout is None:
            return
        self._interval_durations = list(interval_durations)
        t, w = build_target_series(self._workout, self._interval_durations)
        self._interval_target.setData(t, w)
        self._workout_target.setData(t, w)
        total = float(sum(self._interval_durations))
        self._workout_plot.setXRange(0.0, total, padding=0)
        self._update_interval_range(0)

    def update_charts(
        self,
        elapsed_seconds: float,
        current_interval_index: int | None,
        power_series: list[tuple[float, int]],
        hr_series: list[tuple[float, int]],
    ) -> None:
        """Update live traces and position indicator. Called once per second."""
        if self._workout is None:
            return

        for pos in (self._interval_pos, self._workout_pos):
            pos.setValue(float(elapsed_seconds))

        idx = current_interval_index if current_interval_index is not None else 0
        self._update_interval_range(idx)

        # Build numpy arrays
        if power_series:
            pt = np.fromiter((p[0] for p in power_series), dtype=float, count=len(power_series))
            pw = np.fromiter((p[1] for p in power_series), dtype=float, count=len(power_series))
        else:
            pt = pw = np.array([], dtype=float)

        if hr_series:
            ht = np.fromiter((h[0] for h in hr_series), dtype=float, count=len(hr_series))
            hw = np.fromiter((h[1] for h in hr_series), dtype=float, count=len(hr_series))
        else:
            ht = hw = np.array([], dtype=float)

        # Workout overview — full series
        self._workout_actual.setData(pt, pw)
        self._workout_hr.setData(ht, hw)

        # Interval view — slice to visible x window
        x_min, x_max = self._interval_plot.getViewBox().viewRange()[0]

        if pt.size:
            mask = (pt >= x_min) & (pt <= x_max)
            self._interval_actual.setData(pt[mask], pw[mask])
        else:
            self._interval_actual.setData([], [])

        if ht.size:
            mask_hr = (ht >= x_min) & (ht <= x_max)
            self._interval_hr.setData(ht[mask_hr], hw[mask_hr])
        else:
            self._interval_hr.setData([], [])

        # Expand y range if live data exceeds current ceiling
        if pt.size or hw.size:
            peaks = []
            if pt.size:
                peaks.append(float(pw.max()))
            if hw.size:
                peaks.append(float(hw.max()))
            current_ceiling = self._workout_plot.getViewBox().viewRange()[1][1]
            candidate = max(peaks) * 1.10
            if candidate > current_ceiling:
                new_y_max = (int(candidate / _Y_STEP) + 1) * _Y_STEP
                for plot in (self._interval_plot, self._workout_plot):
                    _configure_y_axis(plot, float(new_y_max))

    def export_image(self, path: Path) -> Path:
        """Capture the workout overview chart as a PNG and save it to *path*.

        The raw grab is scaled to ``_EXPORT_WIDTH`` × ``_EXPORT_HEIGHT`` so the
        saved image always has a consistent 16:9 aspect ratio regardless of the
        current window size.
        """
        pixmap = self._workout_plot.grab()
        scaled = pixmap.scaled(
            _EXPORT_WIDTH,
            _EXPORT_HEIGHT,
            Qt.IgnoreAspectRatio,
            Qt.SmoothTransformation,
        )
        scaled.save(str(path), "PNG")
        return path

    def clear(self) -> None:
        """Reset to idle state. Call before loading a new workout."""
        self._workout = None
        self._free_ride_mode = False
        self._free_ride_x_window_seconds = 1800
        for item in (
            self._interval_target, self._interval_actual, self._interval_hr,
            self._workout_target,  self._workout_actual,  self._workout_hr,
        ):
            item.setData([], [])
        for pos in (self._interval_pos, self._workout_pos):
            pos.setValue(0.0)
        for text in (self._interval_ftp_text, self._workout_ftp_text):
            text.setText("")
        self._clear_skip_markers()

    def set_interval_plot_visible(self, visible: bool) -> None:
        """Show or hide the interval plot. When hidden the workout overview expands to fill the area."""
        self._interval_plot.setVisible(visible)
        layout = self.layout()
        if visible:
            layout.setStretchFactor(self._interval_plot, 6)
            layout.setStretchFactor(self._workout_plot, 4)
        else:
            layout.setStretchFactor(self._interval_plot, 0)
            layout.setStretchFactor(self._workout_plot, 1)

    def apply_color_theme(self, color_theme: str) -> None:
        self._color_theme = _COLOR_THEME_DARK if color_theme == _COLOR_THEME_DARK else _COLOR_THEME_LIGHT
        settings = _theme_settings(self._color_theme)

        for plot in (self._interval_plot, self._workout_plot):
            plot.setBackground(settings["background"])
            plot.showGrid(x=False, y=True, alpha=settings["grid_alpha"])
            for axis_name in ("left", "bottom"):
                axis = plot.getAxis(axis_name)
                axis.setPen(pg.mkPen(settings["axis_color"]))
                axis.setTextPen(pg.mkPen(settings["axis_color"]))

        self._interval_pos.setPen(pg.mkPen(settings["position_pen"], width=1))
        self._workout_pos.setPen(pg.mkPen(settings["position_pen"], width=1))
        self._interval_ftp_line.setPen(
            pg.mkPen(color=settings["ftp_line_pen"], width=1, style=Qt.PenStyle.DashLine),
        )
        self._workout_ftp_line.setPen(
            pg.mkPen(color=settings["ftp_line_pen"], width=1, style=Qt.PenStyle.DashLine),
        )
        self._interval_ftp_text.setColor(pg.mkColor(settings["ftp_text_color"]))
        self._workout_ftp_text.setColor(pg.mkColor(settings["ftp_text_color"]))

    def load_free_ride(self) -> None:
        """Prepare the chart for an open-ended free ride with no pre-planned target."""
        self._free_ride_mode = True
        self._free_ride_x_window_seconds = 1800
        self._workout = None
        for item in (
            self._interval_target, self._interval_actual, self._interval_hr,
            self._workout_target,  self._workout_actual,  self._workout_hr,
        ):
            item.setData([], [])
        for pos in (self._interval_pos, self._workout_pos):
            pos.setValue(0.0)
        for text in (self._interval_ftp_text, self._workout_ftp_text):
            text.setText("")
        self._clear_skip_markers()
        self._workout_plot.setXRange(0.0, float(self._free_ride_x_window_seconds), padding=0)
        _configure_y_axis(self._workout_plot, 400.0)

    def update_free_ride_charts(
        self,
        elapsed_seconds: float,
        power_series: list[tuple[float, int]],
        hr_series: list[tuple[float, int]],
    ) -> None:
        """Update live traces on the workout overview chart for free ride mode."""
        while elapsed_seconds >= self._free_ride_x_window_seconds:
            self._free_ride_x_window_seconds += 1800
            self._workout_plot.setXRange(0.0, float(self._free_ride_x_window_seconds), padding=0)

        self._workout_pos.setValue(float(elapsed_seconds))

        if power_series:
            pt = np.fromiter((p[0] for p in power_series), dtype=float, count=len(power_series))
            pw = np.fromiter((p[1] for p in power_series), dtype=float, count=len(power_series))
        else:
            pt = pw = np.array([], dtype=float)

        if hr_series:
            ht = np.fromiter((h[0] for h in hr_series), dtype=float, count=len(hr_series))
            hw = np.fromiter((h[1] for h in hr_series), dtype=float, count=len(hr_series))
        else:
            ht = hw = np.array([], dtype=float)

        self._workout_actual.setData(pt, pw)
        self._workout_hr.setData(ht, hw)

        if pt.size or hw.size:
            peaks = []
            if pt.size:
                peaks.append(float(pw.max()))
            if hw.size:
                peaks.append(float(hw.max()))
            current_ceiling = self._workout_plot.getViewBox().viewRange()[1][1]
            candidate = max(peaks) * 1.10
            if candidate > current_ceiling:
                new_y_max = (int(candidate / _Y_STEP) + 1) * _Y_STEP
                _configure_y_axis(self._workout_plot, float(new_y_max))

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _clear_skip_markers(self) -> None:
        for interval_region, workout_region in self._skip_markers:
            self._interval_plot.removeItem(interval_region)
            self._workout_plot.removeItem(workout_region)
        self._skip_markers.clear()

    def _update_interval_range(self, interval_index: int) -> None:
        if self._workout is None or not self._interval_durations:
            return
        idx = max(0, min(interval_index, len(self._interval_durations) - 1))
        iv_start = float(sum(self._interval_durations[:idx]))
        iv_end   = float(sum(self._interval_durations[:idx + 1]))
        total    = float(sum(self._interval_durations))
        x_min = max(0.0, iv_start - _CONTEXT_SECONDS)
        x_max = min(total, iv_end  + _CONTEXT_SECONDS)
        self._interval_plot.setXRange(x_min, x_max, padding=0)
        self._reposition_ftp_text(self._interval_plot, self._interval_ftp_text)

    def _reposition_ftp_text(
        self,
        plot: pg.PlotWidget,
        text_item: pg.TextItem,
    ) -> None:
        x_max = plot.getViewBox().viewRange()[0][1]
        text_item.setPos(float(x_max), float(self._ftp_watts))


# ── Module-level factory helpers ──────────────────────────────────────────────

def _make_plot() -> pg.PlotWidget:
    plot = pg.PlotWidget(axisItems={"bottom": _TimeAxisItem("bottom")})
    plot.setBackground(_PLOT_BACKGROUND_LIGHT)
    plot.showGrid(x=False, y=True, alpha=_GRID_ALPHA_LIGHT)
    plot.getAxis("left").setTickSpacing(levels=[(_Y_STEP, 0.0)])
    plot.getAxis("left").setLabel("W")
    plot.setMouseEnabled(x=False, y=False)
    plot.setMenuEnabled(False)
    plot.getViewBox().disableAutoRange()
    return plot


def _make_target_item() -> pg.PlotDataItem:
    return pg.PlotDataItem(
        [], [],
        pen=pg.mkPen(color=_TARGET_PEN, width=2),
        fillLevel=0,
        brush=pg.mkBrush(color=_TARGET_FILL),
    )


def _make_actual_item() -> pg.PlotDataItem:
    return pg.PlotDataItem([], [], pen=pg.mkPen(color=_ACTUAL_PEN, width=2), connect="finite")


def _make_hr_item() -> pg.PlotDataItem:
    return pg.PlotDataItem([], [], pen=pg.mkPen(color=_HR_PEN, width=2), connect="finite")


def _make_position_line() -> pg.InfiniteLine:
    return pg.InfiniteLine(
        pos=0, angle=90, movable=False,
        pen=pg.mkPen(color=_POS_PEN, width=1),
    )


def _make_ftp_line() -> pg.InfiniteLine:
    return pg.InfiniteLine(
        pos=0, angle=0, movable=False,
        pen=pg.mkPen(color=_FTP_LINE_PEN, width=1, style=Qt.PenStyle.DashLine),
    )


def _make_ftp_text() -> pg.TextItem:
    item = pg.TextItem(text="", color=_FTP_TEXT_COL, anchor=(1.0, 1.0))
    return item


def _theme_settings(color_theme: str) -> dict[str, object]:
    if color_theme == _COLOR_THEME_DARK:
        return {
            "background": _PLOT_BACKGROUND_DARK,
            "grid_alpha": _GRID_ALPHA_DARK,
            "axis_color": _AXIS_TEXT_DARK,
            "position_pen": _POS_PEN_DARK,
            "ftp_line_pen": _FTP_LINE_PEN_DARK,
            "ftp_text_color": _FTP_TEXT_COL_DARK,
        }
    return {
        "background": _PLOT_BACKGROUND_LIGHT,
        "grid_alpha": _GRID_ALPHA_LIGHT,
        "axis_color": _AXIS_TEXT_LIGHT,
        "position_pen": _POS_PEN,
        "ftp_line_pen": _FTP_LINE_PEN,
        "ftp_text_color": _FTP_TEXT_COL,
    }


def build_target_series(
    workout: Workout,
    interval_durations: list[int] | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Build the target power polyline as (t, w) arrays.

    Each interval contributes two points:
      (start_offset, start_target_watts) and (end_offset, end_target_watts).

    Adjacent flat intervals produce a shared boundary pair that results in a
    correct step (vertical segment).  Ramp intervals produce a sloped line and
    a trapezoidal fill.

    ``interval_durations`` overrides each interval's duration (e.g. after an
    extension), recomputing offsets while keeping the power values unchanged.
    """
    durations = interval_durations if interval_durations is not None else [
        iv.duration_seconds for iv in workout.intervals
    ]
    t: list[float] = []
    w: list[float] = []
    offset = 0
    for iv, dur in zip(workout.intervals, durations):
        t.append(float(offset))
        w.append(float(iv.start_target_watts))
        offset += dur
        t.append(float(offset))
        w.append(float(iv.end_target_watts))
    return np.array(t, dtype=float), np.array(w, dtype=float)


def compute_y_max(workout: Workout, ftp_watts: int) -> float:
    """Return a y ceiling rounded up to the next 50 W grid line."""
    target_peak = max(
        (max(iv.start_target_watts, iv.end_target_watts) for iv in workout.intervals),
        default=0,
    )
    raw = max(float(target_peak), float(ftp_watts)) * 1.10
    return float((int(raw / _Y_STEP) + 1) * _Y_STEP)


def _configure_y_axis(plot: pg.PlotWidget, y_max: float) -> None:
    plot.setYRange(0.0, y_max, padding=0)
    plot.getAxis("left").setTickSpacing(levels=[(_Y_STEP, 0.0)])

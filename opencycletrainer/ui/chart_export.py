"""Off-screen rendering of a finished ride's chart as a shareable PNG.

The live chart is sized for the app window, so a screen grab of it is small and has to be
stretched. This module redraws the ride on its own canvas at the export size, with fonts
and line widths chosen for that size, and with the time axis ending where the ride ended.
"""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
import logging
from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QObject, QPoint, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QImage, QPainter
from PySide6.QtWidgets import QWidget

from . import map_tiles
from .map_export import CourseMapExportData, TileImageLookup, map_tile_keys, paint_map
from .workout_chart import (
    _ACTUAL_PEN,
    _ALPHA1_AXIS_LABEL,
    _ALPHA1_AXIS_MAX,
    _ALPHA1_AXIS_MIN,
    _ALPHA1_PEN,
    _HR_PEN,
    _SKIP_BRUSH,
    _TARGET_FILL,
    _TARGET_PEN,
    _theme_settings,
)

_logger = logging.getLogger(__name__)

# 4:3 landscape: wide enough for a time series, and close to the shape feed tiles are
# cropped to, so little is lost at the edges. Strava publishes no required size.
EXPORT_WIDTH = 1600
EXPORT_HEIGHT = 1200

_MARGIN_PX = 44            # blank border, so a slightly cropped tile keeps the axes
_HEADER_SPACING_PX = 20
_TITLE_FONT_PX = 44
_LEGEND_FONT_PX = 28
_LEGEND_SWATCH_FONT_PX = 16
_LEGEND_GAP_PX = 48        # minimum space between the title and the legend
_AXIS_FONT_PX = 28
_AXIS_TEXT_OFFSET_PX = 14
_AXIS_PADDING_PX = 12      # breathing room around tick text when sizing an axis
_ALPHA1_TICK_STEP = 0.2
_TRACE_WIDTH_PX = 3
_FTP_LINE_WIDTH_PX = 2
_FTP_LABEL_POSITION = 0.985  # fraction of the way along the FTP line

# On course rides the route map sits right of the chart, as on the workout screen.
_MAP_WIDTH_PX = 560
_MAP_GAP_PX = 32

TILE_WAIT_SECONDS = 5.0
"""Longest a course ride's image waits for its map tiles before it is saved with those at hand."""
_MS_PER_SECOND = 1000

# Power is averaged over the time a few pixels cover, so a long ride reads as a line
# rather than a solid band of one-second noise.
_POWER_SMOOTHING_PX = 4
_POINTS_PER_SMOOTHING_WINDOW = 2

_EMPTY_SPAN_SECONDS = 600.0  # axis length when a ride has no samples and no plan
_Y_HEADROOM = 1.10
_Y_ROUND_TO_WATTS = 50.0
_DEFAULT_Y_MAX_WATTS = 300.0
_Y_TICK_STEPS = (50.0, 100.0, 200.0, 500.0)
_MAX_Y_TICKS = 10

_TIME_TICK_STEPS = (5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200)
_MAX_TIME_TICKS = 8
_SECONDS_PER_MINUTE = 60
_SECONDS_PER_HOUR = 3600

Series = tuple[np.ndarray, np.ndarray]


@dataclass(frozen=True)
class ChartExportData:
    """Everything needed to redraw a finished ride, in elapsed-seconds coordinates."""

    title: str
    power: Series
    heart_rate: Series
    target: Series
    alpha1: Series | None = None           # None when the α1 overlay is switched off
    skip_regions: tuple[tuple[float, float], ...] = ()
    ftp_watts: int | None = None
    color_theme: str = "light"
    course_map: CourseMapExportData | None = None  # drawn beside the chart on course rides


def time_tick_step(span_seconds: float) -> int:
    """Return the smallest round step that puts at most eight ticks across the span."""
    for step in _TIME_TICK_STEPS:
        if span_seconds / step <= _MAX_TIME_TICKS:
            return step
    return _TIME_TICK_STEPS[-1]


def format_axis_time(seconds: float, span_seconds: float) -> str:
    """Format a tick as M:SS, or H:MM:SS when the axis covers an hour or more."""
    total = max(0, int(round(seconds)))
    minutes, secs = divmod(total, _SECONDS_PER_MINUTE)
    if span_seconds < _SECONDS_PER_HOUR:
        return f"{minutes}:{secs:02d}"
    hours, minutes = divmod(minutes, _SECONDS_PER_MINUTE)
    return f"{hours}:{minutes:02d}:{secs:02d}"


def ride_end_seconds(data: ChartExportData) -> float:
    """Where the time axis should end: the last recorded sample, else the planned end."""
    last_samples = [float(t[-1]) for t, _ in (data.power, data.heart_rate) if len(t)]
    if last_samples and max(last_samples) > 0.0:
        return max(last_samples)
    planned = data.target[0]
    if len(planned) and float(planned[-1]) > 0.0:
        return float(planned[-1])
    return _EMPTY_SPAN_SECONDS


def y_axis_max(data: ChartExportData, end_seconds: float) -> float:
    """Return a ceiling above everything drawn, rounded up to the next 50 W."""
    peaks = [float(values.max()) for _, values in (data.power, data.heart_rate) if len(values)]
    target_t, target_w = data.target
    if len(target_t):
        ridden = target_t <= end_seconds
        if ridden.any():
            peaks.append(float(target_w[ridden].max()))
    if data.ftp_watts:
        peaks.append(float(data.ftp_watts))
    if not peaks or max(peaks) <= 0.0:
        return _DEFAULT_Y_MAX_WATTS
    return (int(max(peaks) * _Y_HEADROOM / _Y_ROUND_TO_WATTS) + 1) * _Y_ROUND_TO_WATTS


def smooth_for_width(series: Series, span_seconds: float, width_px: int) -> Series:
    """Average *series* over the time a few pixels cover, and thin it to match.

    Gaps (non-finite values) stay gaps. A ride short enough that each sample already has
    its own pixels is returned unchanged.
    """
    t, values = series
    if len(t) < 3 or span_seconds <= 0:
        return series
    window_seconds = span_seconds * _POWER_SMOOTHING_PX / width_px
    sample_seconds = float(np.median(np.diff(t)))
    if sample_seconds <= 0:
        return series
    window = int(round(window_seconds / sample_seconds))
    if window < 2:
        return series
    kernel = np.ones(window)
    finite = np.isfinite(values)
    totals = np.convolve(np.where(finite, values, 0.0), kernel, mode="same")
    counts = np.convolve(finite.astype(float), kernel, mode="same")
    smoothed = np.full(len(values), np.nan)
    np.divide(totals, counts, out=smoothed, where=finite & (counts > 0))
    step = max(1, window // _POINTS_PER_SMOOTHING_WINDOW)
    return t[::step], smoothed[::step]


def render_chart_image(
    data: ChartExportData,
    width: int = EXPORT_WIDTH,
    height: int = EXPORT_HEIGHT,
    *,
    tile_image: TileImageLookup | None = None,
) -> QImage:
    """Draw the ride on an off-screen canvas and return it. Must run on the UI thread.

    A course ride's route map is drawn right of the chart, over whichever map tiles
    *tile_image* has.
    """
    image, map_rect = _render_chart(data, width, height)
    if data.course_map is not None and map_rect is not None:
        paint_map(image, map_rect, data.course_map, tile_image=tile_image, color_theme=data.color_theme)
    return image


def save_chart_image(
    data: ChartExportData, path: Path, *, tile_image: TileImageLookup | None = None,
) -> Path:
    """Render the ride and write it to *path* as a PNG, creating the folder if needed."""
    _write_png(render_chart_image(data, tile_image=tile_image), path)
    return path


class ChartImageExport(QObject):
    """Saves a finished ride's image, first waiting a moment for the map tiles a course ride needs.

    The chart is drawn as soon as the export is made, so the live chart can be cleared
    straight after. On a course ride the map's tiles are then fetched, and the image is
    written once they have all arrived, after TILE_WAIT_SECONDS with those that did, or
    at once when finish_now() is called (the app is closing). Only the tiles the image
    shows are asked for. A ride without a map is written when the export starts.
    """

    finished = Signal(object)
    """Emitted once with the path written, or None if the image could not be written."""

    def __init__(
        self,
        data: ChartExportData,
        path: Path,
        *,
        tile_provider=None,
        wait_seconds: float = TILE_WAIT_SECONDS,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._path = path
        self._course_map = data.course_map
        self._color_theme = data.color_theme
        self._image, self._map_rect = _render_chart(data, EXPORT_WIDTH, EXPORT_HEIGHT)
        self._done = False
        self._listening = False
        self._tiles = None
        self._owns_tiles = False
        self._tile_keys: list = []
        if self._course_map is not None and self._map_rect is not None:
            self._tile_keys = map_tile_keys(self._course_map, self._map_rect.width(), self._map_rect.height())
            if tile_provider is None:
                tile_provider = map_tiles.create_tile_provider(self._course_map.tile_source)
                self._owns_tiles = True
            self._tiles = tile_provider
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(int(wait_seconds * _MS_PER_SECOND))
        self._timer.timeout.connect(self.finish_now)

    @property
    def done(self) -> bool:
        """True once the image has been written (or writing it failed)."""
        return self._done

    def start(self) -> None:
        """Write the image now if nothing is missing, else fetch the map tiles and wait for them."""
        if self._tiles is None or self._has_every_tile():
            self._save()
            return
        self._tiles.tile_ready.connect(self._on_tile_ready)
        self._listening = True
        self._tiles.set_wanted(self._tile_keys)
        self._timer.start()

    def finish_now(self) -> None:
        """Write the image straight away with the tiles at hand; does nothing once written."""
        if not self._done:
            self._save()

    def _on_tile_ready(self, _zoom: int, _x: int, _y: int) -> None:
        if not self._done and self._has_every_tile():
            self._save()

    def _has_every_tile(self) -> bool:
        return all(self._tiles.image(key) is not None for key in self._tile_keys)

    def _save(self) -> None:
        self._done = True
        self._timer.stop()
        if self._course_map is not None and self._map_rect is not None:
            paint_map(
                self._image, self._map_rect, self._course_map,
                tile_image=self._tiles.image if self._tiles is not None else None,
                color_theme=self._color_theme,
            )
        self._release_tiles()
        saved: Path | None = None
        try:
            _write_png(self._image, self._path)
            saved = self._path
        except OSError:
            _logger.exception("Saving the workout chart image failed")
        self.finished.emit(saved)

    def _release_tiles(self) -> None:
        """Stop fetching tiles, and let go of a provider this export made for itself."""
        tiles, self._tiles = self._tiles, None
        if tiles is None:
            return
        if self._listening:
            tiles.tile_ready.disconnect(self._on_tile_ready)
            self._listening = False
        tiles.set_wanted([])
        if self._owns_tiles and isinstance(tiles, QObject):
            tiles.deleteLater()


def _write_png(image: QImage, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not image.save(str(path), "PNG"):
        raise OSError(f"Could not write chart image to {path}")


def _render_chart(data: ChartExportData, width: int, height: int) -> tuple[QImage, QRectF | None]:
    """Draw everything but the map; return the image and, on course rides, the rectangle left for the map."""
    theme = _theme_settings(data.color_theme)
    text_color = QColor(*theme["axis_color"])
    end_seconds = ride_end_seconds(data)

    canvas = pg.GraphicsLayoutWidget()
    canvas.setBackground(theme["background"])
    canvas.resize(width, height)
    canvas.ci.layout.setContentsMargins(_MARGIN_PX, _MARGIN_PX, _MARGIN_PX, _MARGIN_PX)
    canvas.ci.layout.setVerticalSpacing(_HEADER_SPACING_PX)

    legend = pg.LabelItem(justify="right")
    legend.setText(_legend_html(data), color=text_color.name(), size=f"{_LEGEND_FONT_PX}px")
    title = pg.LabelItem(justify="left")
    title_room = width - 2 * _MARGIN_PX - legend.item.boundingRect().width() - _LEGEND_GAP_PX
    title.setText(
        escape(_elide(data.title, title_room)),
        color=text_color.name(), size=f"{_TITLE_FONT_PX}px", bold=True,
    )
    canvas.addItem(title, row=0, col=0)
    canvas.addItem(legend, row=0, col=1)

    plot = pg.PlotItem(axisItems={"bottom": _ExportTimeAxis("bottom")})
    map_room = None
    plot_width = width
    if data.course_map is None:
        canvas.addItem(plot, row=1, col=0, colspan=2)
    else:
        body = canvas.addLayout(row=1, col=0, colspan=2)
        body.setContentsMargins(0, 0, 0, 0)
        body.layout.setHorizontalSpacing(_MAP_GAP_PX)
        body.addItem(plot, row=0, col=0)
        map_room = pg.GraphicsWidget()
        map_room.setMinimumWidth(_MAP_WIDTH_PX)
        map_room.setMaximumWidth(_MAP_WIDTH_PX)
        body.addItem(map_room, row=0, col=1)
        plot_width = width - _MAP_WIDTH_PX - _MAP_GAP_PX
    _style_plot(plot, theme)
    plot.setXRange(0.0, end_seconds, padding=0)
    y_max = y_axis_max(data, end_seconds)
    _set_y_range(plot, y_max)
    left_axis = plot.getAxis("left")
    left_axis.setLabel("W / bpm" if len(data.heart_rate[0]) else "W", **_axis_label_style(text_color))
    left_axis.setWidth(_side_axis_width(f"{int(y_max)}"))

    for start, end in data.skip_regions:
        plot.addItem(pg.LinearRegionItem(
            values=[start, end], orientation="vertical",
            brush=pg.mkBrush(_SKIP_BRUSH), pen=pg.mkPen(None), movable=False,
        ))
    if len(data.target[0]):
        plot.addItem(pg.PlotDataItem(
            *data.target, pen=_trace_pen(_TARGET_PEN), fillLevel=0,
            brush=pg.mkBrush(color=_TARGET_FILL), antialias=True,
        ))
    if data.ftp_watts:
        plot.addItem(_ftp_line(data.ftp_watts, theme))
    plot.addItem(_trace(data.heart_rate, _HR_PEN))
    plot.addItem(_trace(smooth_for_width(data.power, end_seconds, plot_width), _ACTUAL_PEN))

    alpha1_view = _add_alpha1_axis(plot, data.alpha1, text_color) if data.alpha1 is not None else None

    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(QColor(*theme["background"]))
    painter = QPainter(image)
    try:
        # QWidget.render (not the scene-only QGraphicsView overload) lays the unshown
        # widget out first and paints at the image's own pixel ratio.
        QWidget.render(canvas, painter, QPoint(0, 0))
    finally:
        painter.end()
    map_rect = None
    if map_room is not None:
        # The map spans the plot's data area top to bottom; the canvas draws at scene scale.
        data_area = plot.getViewBox().sceneBoundingRect()
        room = map_room.sceneBoundingRect()
        map_rect = QRectF(room.left(), data_area.top(), room.width(), data_area.height())
    if alpha1_view is not None:
        canvas.scene().removeItem(alpha1_view)
    canvas.deleteLater()
    return image, map_rect


# ── Drawing helpers ───────────────────────────────────────────────────────────

class _ExportTimeAxis(pg.AxisItem):
    """Bottom axis with round time steps and labels that grow an hours field when needed."""

    def tickValues(self, minVal: float, maxVal: float, size: float) -> list:  # noqa: N802, N803, ARG002
        span = maxVal - minVal
        if span <= 0:
            return []
        step = time_tick_step(span)
        first = np.ceil(minVal / step) * step
        return [(step, list(np.arange(first, maxVal + step * 1e-6, step)))]

    def tickStrings(self, values: list, scale: float, spacing: float) -> list[str]:  # noqa: N802, ARG002
        low, high = self.range
        return [format_axis_time(value, high - low) for value in values]


def _axis_font() -> QFont:
    font = QFont()
    font.setPixelSize(_AXIS_FONT_PX)
    return font


def _axis_label_style(color: QColor) -> dict[str, str]:
    return {"font-size": f"{_AXIS_FONT_PX}px", "color": color.name()}


def _style_plot(plot: pg.PlotItem, theme: dict[str, object]) -> None:
    plot.setMenuEnabled(False)
    plot.hideButtons()
    plot.getViewBox().disableAutoRange()
    plot.showGrid(x=False, y=True, alpha=theme["grid_alpha"])
    for name in ("left", "bottom"):
        _style_axis(plot.getAxis(name), theme["axis_color"])
    bottom_axis = plot.getAxis("bottom")
    bottom_axis.setHeight(_AXIS_FONT_PX + _AXIS_TEXT_OFFSET_PX + _AXIS_PADDING_PX)
    # Let a label near the end of the ride run into the border instead of being dropped.
    bottom_axis.setStyle(hideOverlappingLabels=_MARGIN_PX)


def _style_axis(axis: pg.AxisItem, color: object) -> None:
    axis.setPen(pg.mkPen(color))
    axis.setTextPen(pg.mkPen(color))
    axis.setStyle(tickFont=_axis_font(), tickTextOffset=_AXIS_TEXT_OFFSET_PX)


def _side_axis_width(widest_tick_text: str) -> int:
    """Width for a labelled vertical axis: its rotated label beside its tick text."""
    text_width = QFontMetrics(_axis_font()).horizontalAdvance(widest_tick_text)
    return _AXIS_FONT_PX + _AXIS_PADDING_PX + text_width + _AXIS_TEXT_OFFSET_PX + _AXIS_PADDING_PX


def _set_y_range(plot: pg.PlotItem, y_max: float) -> None:
    plot.setYRange(0.0, y_max, padding=0)
    step = next((s for s in _Y_TICK_STEPS if y_max / s <= _MAX_Y_TICKS), _Y_TICK_STEPS[-1])
    plot.getAxis("left").setTickSpacing(levels=[(step, 0.0)])


def _trace_pen(color: tuple[int, ...]) -> object:
    return pg.mkPen(color=color, width=_TRACE_WIDTH_PX)


def _trace(series: Series, color: tuple[int, ...]) -> pg.PlotDataItem:
    return pg.PlotDataItem(*series, pen=_trace_pen(color), connect="finite", antialias=True)


def _ftp_line(ftp_watts: int, theme: dict[str, object]) -> pg.InfiniteLine:
    line = pg.InfiniteLine(
        pos=float(ftp_watts), angle=0, movable=False,
        pen=pg.mkPen(color=theme["ftp_line_pen"], width=_FTP_LINE_WIDTH_PX, style=Qt.PenStyle.DashLine),
        label="FTP",
        labelOpts={"position": _FTP_LABEL_POSITION, "color": theme["ftp_text_color"], "anchors": [(1, 1), (1, 1)]},
    )
    line.label.setFont(_axis_font())
    return line


def _add_alpha1_axis(plot: pg.PlotItem, series: Series, text_color: QColor) -> pg.ViewBox:
    """Draw α1 against its own fixed-range axis on the right-hand side."""
    view = pg.ViewBox()
    plot.showAxis("right")
    plot.scene().addItem(view)
    axis = plot.getAxis("right")
    axis.linkToView(view)
    _style_axis(axis, text_color)
    axis.setLabel(_ALPHA1_AXIS_LABEL, **_axis_label_style(text_color))
    axis.setTickSpacing(levels=[(_ALPHA1_TICK_STEP, 0.0)])
    axis.setWidth(_side_axis_width(f"{_ALPHA1_AXIS_MAX:.1f}"))
    axis.setGrid(False)  # showGrid() switches both vertical axes on; keep one set of lines
    view.setXLink(plot)
    view.setYRange(_ALPHA1_AXIS_MIN, _ALPHA1_AXIS_MAX, padding=0)

    def sync_geometry() -> None:
        view.setGeometry(plot.vb.sceneBoundingRect())
        view.linkedViewChanged(plot.vb, view.XAxis)

    plot.vb.sigResized.connect(sync_geometry)
    sync_geometry()
    view.addItem(_trace(series, _ALPHA1_PEN))
    return view


def _legend_html(data: ChartExportData) -> str:
    entries = [("Power", _ACTUAL_PEN)]
    if len(data.heart_rate[0]):
        entries.append(("Heart rate", _HR_PEN))
    if len(data.target[0]):
        entries.append(("Target", _TARGET_PEN))
    if data.alpha1 is not None:
        entries.append((_ALPHA1_AXIS_LABEL, _ALPHA1_PEN))
    swatch = (
        '<span style="background-color:{color}; font-size:{size}px">&nbsp;&nbsp;&nbsp;&nbsp;</span>'
        "&nbsp;{name}"
    )
    return "&nbsp;&nbsp;&nbsp;&nbsp;".join(
        swatch.format(color=QColor(*color[:3]).name(), size=_LEGEND_SWATCH_FONT_PX, name=name)
        for name, color in entries
    )


def _elide(text: str, width_px: float) -> str:
    font = QFont()
    font.setPixelSize(_TITLE_FONT_PX)
    font.setBold(True)
    return QFontMetrics(font).elidedText(text, Qt.TextElideMode.ElideRight, int(max(0.0, width_px)))


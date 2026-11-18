from __future__ import annotations

import math
import os

os.environ.setdefault("PYQTGRAPH_QT_LIB", "PySide6")

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QToolButton, QWidget

from opencycletrainer.core.course_model import Course

from . import map_tiles
from .map_tiles import OPENSTREETMAP, TileKey, TileSource, tile_bounds, tile_zoom_for, visible_tiles

# Web Mercator (EPSG:3857), the projection map tiles are drawn in.
_EARTH_RADIUS_M = 6_378_137.0
_TILE_SIZE_PX = 256
_MERCATOR_WORLD_WIDTH_M = 2.0 * math.pi * _EARTH_RADIUS_M

DEFAULT_FOLLOW_ZOOM = 15
"""Tile zoom level the map follows the rider at: a few streets either side at road scale."""
MIN_FOLLOW_ZOOM = 10
MAX_FOLLOW_ZOOM = 18

_FALLBACK_VIEW_SIZE_PX = (300.0, 400.0)  # used until the map has been laid out
_WHOLE_ROUTE_PADDING_RATIO = 0.08         # margin around the route in the whole-route view
_MIN_WHOLE_ROUTE_SPAN_M = 200.0           # a tiny route still gets a sensible view

_AHEAD_PEN = (220, 38, 38)        # red: road still to ride
_RIDDEN_PEN = (34, 197, 94)       # green: road already ridden
_ROUTE_PEN_WIDTH = 4
_RIDER_DOT_SIZE = 11
_RIDER_DOT_PEN = (30, 41, 59)
_RIDER_DOT_BRUSH = (255, 255, 255)
_MARKER_SIZE = 10
_START_BRUSH = (34, 197, 94)
_FINISH_BRUSH = (15, 23, 42)
_MARKER_PEN = (255, 255, 255)

_BACKGROUND_LIGHT = (241, 245, 249)
_BACKGROUND_DARK = (30, 41, 59)
_COLOR_THEME_DARK = "dark"

_BUTTON_MARGIN_PX = 4
_BUTTON_SPACING_PX = 2
_FOLLOW_TEXT = "Follow"
_WHOLE_ROUTE_TEXT = "Whole route"
_ZOOM_IN_TEXT = "+"
_ZOOM_OUT_TEXT = "−"

_TILE_Z_VALUE = -10             # map tiles sit under the route
_RGBA_CHANNELS = 4
_RGBA_LEVELS = (0, 255)
_ATTRIBUTION_STYLE = (
    "QLabel { background: rgba(255, 255, 255, 190); color: #1e293b; padding: 1px 4px; }"
)
_ATTRIBUTION_FONT_SIZE_DELTA = -2

_COLLAPSE_BUTTON_WIDTH_PX = 16
_QWIDGETSIZE_MAX = (1 << 24) - 1  # Qt's "no maximum" widget size
_COLLAPSE_TEXT = "›"  # › tucks the map away to the right
_EXPAND_TEXT = "‹"    # ‹ brings it back
_COLLAPSE_TOOLTIP = "Hide the map"
_EXPAND_TOOLTIP = "Show the map"


def mercator_xy(latitude_deg: float, longitude_deg: float) -> tuple[float, float]:
    """Project a coordinate to Web Mercator metres (x east, y north), as map tiles are drawn."""
    x = _EARTH_RADIUS_M * math.radians(longitude_deg)
    y = _EARTH_RADIUS_M * math.log(math.tan(math.pi / 4.0 + math.radians(latitude_deg) / 2.0))
    return x, y


def _mercator_metres_per_pixel(zoom: int) -> float:
    """Return the Web Mercator metres one screen pixel covers at tile zoom level *zoom*."""
    return _MERCATOR_WORLD_WIDTH_M / (_TILE_SIZE_PX * 2 ** zoom)


class CourseMapWidget(QWidget):
    """Top-down map of a course: the road still to ride in red, the ridden road in green.

    The route is drawn from the course's own coordinates, so it needs no network; map
    tiles from *tile_provider* (by default one for *tile_source*) are drawn underneath as
    they arrive. The view either follows the rider at a tile zoom level or shows the whole route.
    """

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        tile_provider=None,
        tile_source: TileSource = OPENSTREETMAP,
    ) -> None:
        super().__init__(parent)
        self._tiles = (
            tile_provider if tile_provider is not None else map_tiles.create_tile_provider(tile_source)
        )
        self._tiles.tile_ready.connect(self._on_tile_ready)
        self._tile_items: dict[TileKey, pg.ImageItem] = {}
        self._visible_tile_keys: set[TileKey] = set()
        self._course: Course | None = None
        self._distances = np.array([], dtype=float)
        self._xs = np.array([], dtype=float)
        self._ys = np.array([], dtype=float)
        self._lap_bounds: list[tuple[int, int]] = []
        self._position_m = 0.0
        self._rider_xy: tuple[float, float] = (0.0, 0.0)
        self._following = True
        self._zoom_level = DEFAULT_FOLLOW_ZOOM

        self._plot = pg.PlotWidget()
        self._plot.hideAxis("left")
        self._plot.hideAxis("bottom")
        self._plot.setMouseEnabled(x=False, y=False)
        self._plot.setMenuEnabled(False)
        self._plot.getPlotItem().hideButtons()
        self._plot.getViewBox().disableAutoRange()
        self._plot.getViewBox().sigResized.connect(lambda _vb: self._on_resized())

        self._ahead_item = pg.PlotDataItem([], [], pen=pg.mkPen(color=_AHEAD_PEN, width=_ROUTE_PEN_WIDTH))
        self._ridden_item = pg.PlotDataItem([], [], pen=pg.mkPen(color=_RIDDEN_PEN, width=_ROUTE_PEN_WIDTH))
        self._start_marker = pg.ScatterPlotItem(
            size=_MARKER_SIZE, symbol="o", pen=pg.mkPen(_MARKER_PEN), brush=pg.mkBrush(_START_BRUSH)
        )
        self._finish_marker = pg.ScatterPlotItem(
            size=_MARKER_SIZE, symbol="s", pen=pg.mkPen(_MARKER_PEN), brush=pg.mkBrush(_FINISH_BRUSH)
        )
        self._dot = pg.ScatterPlotItem(
            size=_RIDER_DOT_SIZE,
            pen=pg.mkPen(color=_RIDER_DOT_PEN, width=2),
            brush=pg.mkBrush(_RIDER_DOT_BRUSH),
        )
        for item in (
            self._ahead_item, self._ridden_item, self._start_marker, self._finish_marker, self._dot,
        ):
            self._plot.addItem(item)

        self.follow_button = self._make_overlay_button(_WHOLE_ROUTE_TEXT)
        self.follow_button.setToolTip("Switch between following the rider and the whole route")
        self.follow_button.clicked.connect(lambda: self.set_following(not self._following))
        self.zoom_in_button = self._make_overlay_button(_ZOOM_IN_TEXT)
        self.zoom_in_button.setToolTip("Zoom in")
        self.zoom_in_button.clicked.connect(lambda: self._set_zoom(self._zoom_level + 1))
        self.zoom_out_button = self._make_overlay_button(_ZOOM_OUT_TEXT)
        self.zoom_out_button.setToolTip("Zoom out")
        self.zoom_out_button.clicked.connect(lambda: self._set_zoom(self._zoom_level - 1))
        self.attribution_label = QLabel(self._tiles.source.attribution, self._plot)
        self.attribution_label.setStyleSheet(_ATTRIBUTION_STYLE)
        attribution_font = self.attribution_label.font()
        attribution_font.setPointSize(max(1, attribution_font.pointSize() + _ATTRIBUTION_FONT_SIZE_DELTA))
        self.attribution_label.setFont(attribution_font)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._plot)
        self.apply_color_theme("light")
        self._update_zoom_buttons()

    @property
    def has_route(self) -> bool:
        """True while a course with coordinates is loaded."""
        return self._course is not None

    @property
    def following(self) -> bool:
        """True while the view is centred on the rider, False while it shows the whole route."""
        return self._following

    @property
    def zoom_level(self) -> int:
        """Tile zoom level used while following the rider."""
        return self._zoom_level

    def load_course(self, course: Course) -> None:
        """Draw *course*'s route with the rider at its start; a course without coordinates draws nothing."""
        self.clear()
        located = [(point.latitude_deg, point.longitude_deg) for point in course.points]
        if any(lat is None or lon is None for lat, lon in located):
            return
        self._course = course
        self._distances = np.array([point.distance_m for point in course.points], dtype=float)
        projected = [mercator_xy(lat, lon) for lat, lon in located]
        self._xs = np.array([x for x, _ in projected], dtype=float)
        self._ys = np.array([y for _, y in projected], dtype=float)
        self._lap_bounds = self._find_lap_bounds(course)
        self._start_marker.setData([self._xs[0]], [self._ys[0]])
        self._finish_marker.setData([self._xs[-1]], [self._ys[-1]])
        self.set_position(0.0)
        self._apply_view()

    def clear(self) -> None:
        """Remove the route and rider from the map."""
        self._course = None
        self._distances = np.array([], dtype=float)
        self._xs = np.array([], dtype=float)
        self._ys = np.array([], dtype=float)
        self._lap_bounds = []
        self._position_m = 0.0
        for item in (
            self._ahead_item, self._ridden_item, self._start_marker, self._finish_marker, self._dot,
        ):
            item.setData([], [])
        self._show_tiles([])

    def set_position(self, distance_m: float) -> None:
        """Place the rider *distance_m* along the course and colour the lap being ridden."""
        course = self._course
        if course is None:
            return
        distance = min(max(0.0, float(distance_m)), float(course.total_distance_m))
        self._position_m = distance
        latitude, longitude = course.position_at(distance)
        self._rider_xy = mercator_xy(latitude, longitude)
        self._dot.setData([self._rider_xy[0]], [self._rider_xy[1]])

        first, past = self._lap_bounds[course.lap_number_at(distance) - 1]
        lap_distances = self._distances[first:past]
        split = first + int(np.searchsorted(lap_distances, distance, side="right"))
        rider_x, rider_y = self._rider_xy
        if distance <= self._distances[first]:
            self._ridden_item.setData([], [])
        else:
            self._ridden_item.setData(
                np.append(self._xs[first:split], rider_x), np.append(self._ys[first:split], rider_y)
            )
        self._ahead_item.setData(
            np.concatenate(([rider_x], self._xs[split:past])),
            np.concatenate(([rider_y], self._ys[split:past])),
        )
        if self._following:
            self._apply_view()

    def set_following(self, following: bool) -> None:
        """Follow the rider at the current zoom level, or show the whole route."""
        self._following = bool(following)
        self.follow_button.setText(_WHOLE_ROUTE_TEXT if self._following else _FOLLOW_TEXT)
        self._update_zoom_buttons()
        self._apply_view()

    def set_tile_source(self, source: TileSource) -> None:
        """Draw the map from *source*'s tiles instead, dropping the tiles already shown."""
        if source == self._tiles.source:
            return
        self._tiles.set_wanted([])
        self._tiles.tile_ready.disconnect(self._on_tile_ready)
        for item in self._tile_items.values():
            self._plot.removeItem(item)
        self._tile_items.clear()
        self._tiles = map_tiles.create_tile_provider(source)
        self._tiles.tile_ready.connect(self._on_tile_ready)
        self.attribution_label.setText(source.attribution)
        self._place_overlay_buttons()
        self._apply_view()

    def apply_color_theme(self, color_theme: str) -> None:
        """Match the map's background to the light or dark theme."""
        dark = color_theme == _COLOR_THEME_DARK
        self._plot.setBackground(_BACKGROUND_DARK if dark else _BACKGROUND_LIGHT)

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().resizeEvent(event)
        self._place_overlay_buttons()

    def _set_zoom(self, zoom: int) -> None:
        self._zoom_level = min(max(int(zoom), MIN_FOLLOW_ZOOM), MAX_FOLLOW_ZOOM)
        self._update_zoom_buttons()
        self._apply_view()

    def _update_zoom_buttons(self) -> None:
        self.zoom_in_button.setEnabled(self._following and self._zoom_level < MAX_FOLLOW_ZOOM)
        self.zoom_out_button.setEnabled(self._following and self._zoom_level > MIN_FOLLOW_ZOOM)

    def _on_resized(self) -> None:
        self._place_overlay_buttons()
        self._apply_view()

    def _view_size_px(self) -> tuple[float, float]:
        """Size of the drawing area in pixels, or a stand-in before it has been laid out."""
        view_box = self._plot.getViewBox()
        width, height = float(view_box.width()), float(view_box.height())
        if width < 1.0 or height < 1.0:
            return _FALLBACK_VIEW_SIZE_PX
        return width, height

    def _apply_view(self) -> None:
        """Frame the rider at the zoom level, or the whole route, keeping the map's true shape."""
        if self._course is None:
            return
        width_px, height_px = self._view_size_px()
        if self._following:
            metres_per_px = _mercator_metres_per_pixel(self._zoom_level)
            centre_x, centre_y = self._rider_xy
        else:
            span_x = max(float(np.ptp(self._xs)), _MIN_WHOLE_ROUTE_SPAN_M)
            span_y = max(float(np.ptp(self._ys)), _MIN_WHOLE_ROUTE_SPAN_M)
            padded = 1.0 + 2.0 * _WHOLE_ROUTE_PADDING_RATIO
            metres_per_px = max(span_x * padded / width_px, span_y * padded / height_px)
            centre_x = (float(np.min(self._xs)) + float(np.max(self._xs))) / 2.0
            centre_y = (float(np.min(self._ys)) + float(np.max(self._ys))) / 2.0
        half_width = width_px * metres_per_px / 2.0
        half_height = height_px * metres_per_px / 2.0
        view = (centre_x - half_width, centre_x + half_width, centre_y - half_height, centre_y + half_height)
        self._plot.setRange(xRange=view[:2], yRange=view[2:], padding=0)
        max_zoom = self._tiles.source.max_zoom
        if self._following:
            tile_zoom = min(self._zoom_level, max_zoom)
        else:
            tile_zoom = tile_zoom_for(metres_per_px, max_zoom=max_zoom)
        self._show_tiles(visible_tiles(view, tile_zoom))

    def _show_tiles(self, keys: list[TileKey]) -> None:
        """Draw the tiles in view that are already at hand, drop the rest, and ask for the missing."""
        self._visible_tile_keys = set(keys)
        for key in [key for key in self._tile_items if key not in self._visible_tile_keys]:
            self._plot.removeItem(self._tile_items.pop(key))
        for key in keys:
            if key not in self._tile_items:
                image = self._tiles.image(key)
                if image is not None:
                    self._draw_tile(key, image)
        self._tiles.set_wanted(keys)

    def _on_tile_ready(self, zoom: int, x: int, y: int) -> None:
        key = (zoom, x, y)
        if key in self._visible_tile_keys and key not in self._tile_items:
            image = self._tiles.image(key)
            if image is not None:
                self._draw_tile(key, image)

    def _draw_tile(self, key: TileKey, image: QImage) -> None:
        """Place a tile's image over its patch of the map, beneath the route."""
        item = pg.ImageItem(axisOrder="row-major")
        item.setImage(_rgba_rows_south_first(image), levels=_RGBA_LEVELS, autoLevels=False)
        x_min, y_min, x_max, y_max = tile_bounds(*key)
        item.setRect(QRectF(x_min, y_min, x_max - x_min, y_max - y_min))
        item.setZValue(_TILE_Z_VALUE)
        self._plot.addItem(item)
        self._tile_items[key] = item

    def _make_overlay_button(self, text: str) -> QToolButton:
        button = QToolButton(self._plot)
        button.setText(text)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        return button

    def _place_overlay_buttons(self) -> None:
        """Stack the view buttons in the top-right corner of the map."""
        x_right = self._plot.width() - _BUTTON_MARGIN_PX
        y = _BUTTON_MARGIN_PX
        for button in (self.follow_button, self.zoom_in_button, self.zoom_out_button):
            button.adjustSize()
            button.move(max(0, x_right - button.width()), y)
            y += button.height() + _BUTTON_SPACING_PX
        self.attribution_label.adjustSize()
        self.attribution_label.move(
            max(0, self._plot.width() - self.attribution_label.width()),
            max(0, self._plot.height() - self.attribution_label.height()),
        )

    @staticmethod
    def _find_lap_bounds(course: Course) -> list[tuple[int, int]]:
        """Return each lap's (first, past-the-end) point indices.

        Laps share the same road, so only the lap being ridden is drawn.
        """
        distances = [point.distance_m for point in course.points]
        starts = course.lap_starts_m
        bounds: list[tuple[int, int]] = []
        for index, lap_start in enumerate(starts):
            first = 0 if index == 0 else int(np.searchsorted(distances, lap_start, side="right")) - 1
            if index + 1 < len(starts):
                past = int(np.searchsorted(distances, starts[index + 1], side="left")) + 1
            else:
                past = len(distances)
            bounds.append((first, past))
        return bounds


def _rgba_rows_south_first(image: QImage) -> np.ndarray:
    """Return a tile as an RGBA array with its southern row first, as the map's y axis runs north."""
    rgba = image.convertToFormat(QImage.Format.Format_RGBA8888)
    width, height = rgba.width(), rgba.height()
    raw = np.frombuffer(rgba.constBits(), dtype=np.uint8, count=rgba.sizeInBytes())
    rows = raw.reshape(height, rgba.bytesPerLine())[:, : width * _RGBA_CHANNELS]
    return rows.reshape(height, width, _RGBA_CHANNELS)[::-1].copy()


class CourseMapPanel(QWidget):
    """The course map with a slim button on its left edge that tucks it away and brings it back."""

    collapsed_changed = Signal(bool)

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        tile_provider=None,
        tile_source: TileSource = OPENSTREETMAP,
    ) -> None:
        super().__init__(parent)
        self._collapsed = False
        self.collapse_button = QToolButton(self)
        self.collapse_button.setFixedWidth(_COLLAPSE_BUTTON_WIDTH_PX)
        self.collapse_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.collapse_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.collapse_button.clicked.connect(lambda: self.set_collapsed(not self._collapsed))
        self.map_widget = CourseMapWidget(self, tile_provider=tile_provider, tile_source=tile_source)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.collapse_button)
        layout.addWidget(self.map_widget, 1)
        self._show_collapsed_state()

    @property
    def collapsed(self) -> bool:
        return self._collapsed

    @property
    def has_route(self) -> bool:
        return self.map_widget.has_route

    def set_collapsed(self, collapsed: bool) -> None:
        """Hide the map behind its edge button, or show it again."""
        self._collapsed = bool(collapsed)
        self._show_collapsed_state()
        self.collapsed_changed.emit(self._collapsed)

    def load_course(self, course: Course) -> None:
        self.map_widget.load_course(course)

    def set_position(self, distance_m: float) -> None:
        self.map_widget.set_position(distance_m)

    def clear(self) -> None:
        self.map_widget.clear()

    def set_tile_source(self, source: TileSource) -> None:
        self.map_widget.set_tile_source(source)

    def apply_color_theme(self, color_theme: str) -> None:
        self.map_widget.apply_color_theme(color_theme)

    def _show_collapsed_state(self) -> None:
        """Narrow the panel to its edge button while collapsed, so the plots take the room."""
        self.setMaximumWidth(_COLLAPSE_BUTTON_WIDTH_PX if self._collapsed else _QWIDGETSIZE_MAX)
        self.map_widget.setVisible(not self._collapsed)
        self.collapse_button.setText(_EXPAND_TEXT if self._collapsed else _COLLAPSE_TEXT)
        self.collapse_button.setToolTip(_EXPAND_TOOLTIP if self._collapsed else _COLLAPSE_TOOLTIP)

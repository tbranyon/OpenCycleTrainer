"""Drawing a course ride's route map into the saved ride image.

The map shows the whole route, the road ridden in green and any road left in red, the
same as the live map, at sizes chosen for the export rather than the screen. Map tiles
are drawn underneath when they are at hand; without them the route sits on a plain
background.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetrics, QImage, QPainter, QPen, QPolygonF

from .course_map import (
    _AHEAD_PEN,
    _BACKGROUND_DARK,
    _BACKGROUND_LIGHT,
    _COLOR_THEME_DARK,
    _FINISH_BRUSH,
    _MARKER_PEN,
    _RIDDEN_PEN,
    _RIDER_DOT_BRUSH,
    _RIDER_DOT_PEN,
    _START_BRUSH,
)
from .map_tiles import OPENSTREETMAP, TileKey, TileSource, fit_view, tile_bounds, tile_zoom_for, visible_tiles

Series = tuple[np.ndarray, np.ndarray]
Point = tuple[float, float]
TileImageLookup = Callable[[TileKey], "QImage | None"]

_ROUTE_WIDTH_PX = 6
_MARKER_SIZE_PX = 18
_MARKER_PEN_WIDTH_PX = 2
_RIDER_DOT_SIZE_PX = 22
_RIDER_DOT_PEN_WIDTH_PX = 3
_ATTRIBUTION_FONT_PX = 18
_ATTRIBUTION_PADDING_PX = 6
_ATTRIBUTION_BACKGROUND = (255, 255, 255, 190)
_ATTRIBUTION_TEXT = (30, 41, 59)


@dataclass(frozen=True)
class CourseMapExportData:
    """A course ride's map as it stood at the end: the road ridden, the road ahead and the rider.

    Positions are Web Mercator metres, as the live map draws them.
    """

    ridden: Series
    ahead: Series
    start: Point
    finish: Point
    rider: Point
    tile_source: TileSource = OPENSTREETMAP


def map_view(
    data: CourseMapExportData, width_px: float, height_px: float,
) -> tuple[tuple[float, float, float, float], float]:
    """Return the view (x_min, x_max, y_min, y_max) that shows the whole route, and its metres per pixel."""
    xs = np.concatenate((data.ridden[0], data.ahead[0], [data.start[0], data.finish[0], data.rider[0]]))
    ys = np.concatenate((data.ridden[1], data.ahead[1], [data.start[1], data.finish[1], data.rider[1]]))
    return fit_view(xs, ys, width_px, height_px)


def map_tile_keys(data: CourseMapExportData, width_px: float, height_px: float) -> list[TileKey]:
    """Return the tiles a map of *width_px* × *height_px* needs, at the zoom matching its scale."""
    view, metres_per_px = map_view(data, width_px, height_px)
    return _tiles_for_view(view, metres_per_px, data.tile_source)


def _tiles_for_view(
    view: tuple[float, float, float, float], metres_per_px: float, source: TileSource,
) -> list[TileKey]:
    return visible_tiles(view, tile_zoom_for(metres_per_px, max_zoom=source.max_zoom))


def paint_map(
    image: QImage,
    rect: QRectF,
    data: CourseMapExportData,
    *,
    tile_image: TileImageLookup | None = None,
    color_theme: str = "light",
) -> None:
    """Draw the route map into *rect* of *image*, over whichever tiles *tile_image* has.

    The tile source is credited whenever any of its tiles are drawn.
    """
    view, metres_per_px = map_view(data, rect.width(), rect.height())
    x_min, _, _, y_max = view

    def to_px(x: float, y: float) -> QPointF:
        return QPointF(rect.left() + (x - x_min) / metres_per_px, rect.top() + (y_max - y) / metres_per_px)

    background = _BACKGROUND_DARK if color_theme == _COLOR_THEME_DARK else _BACKGROUND_LIGHT
    painter = QPainter(image)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.setClipRect(rect)
        painter.fillRect(rect, QColor(*background))
        tiles_drawn = False
        if tile_image is not None:
            for key in _tiles_for_view(view, metres_per_px, data.tile_source):
                tile = tile_image(key)
                if tile is not None:
                    tile_x_min, tile_y_min, tile_x_max, tile_y_max = tile_bounds(*key)
                    painter.drawImage(
                        _pixel_aligned(to_px(tile_x_min, tile_y_max), to_px(tile_x_max, tile_y_min)), tile,
                    )
                    tiles_drawn = True
        for series, color in ((data.ahead, _AHEAD_PEN), (data.ridden, _RIDDEN_PEN)):
            _draw_line(painter, [to_px(x, y) for x, y in zip(*series)], color)
        _draw_marker(painter, to_px(*data.start), _START_BRUSH, square=False)
        _draw_marker(painter, to_px(*data.finish), _FINISH_BRUSH, square=True)
        painter.setPen(QPen(QColor(*_RIDER_DOT_PEN), _RIDER_DOT_PEN_WIDTH_PX))
        painter.setBrush(QBrush(QColor(*_RIDER_DOT_BRUSH)))
        painter.drawEllipse(to_px(*data.rider), _RIDER_DOT_SIZE_PX / 2, _RIDER_DOT_SIZE_PX / 2)
        if tiles_drawn:
            _draw_attribution(painter, rect, data.tile_source.attribution)
    finally:
        painter.end()


def _pixel_aligned(top_left: QPointF, bottom_right: QPointF) -> QRectF:
    """Round a tile's corners to whole pixels, so neighbouring tiles meet without a seam."""
    return QRectF(
        QPointF(round(top_left.x()), round(top_left.y())),
        QPointF(round(bottom_right.x()), round(bottom_right.y())),
    )


def _draw_line(painter: QPainter, points: list[QPointF], color: tuple[int, int, int]) -> None:
    if len(points) < 2:
        return
    pen = QPen(QColor(*color), _ROUTE_WIDTH_PX)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPolyline(QPolygonF(points))


def _draw_marker(painter: QPainter, centre: QPointF, color: tuple[int, int, int], *, square: bool) -> None:
    painter.setPen(QPen(QColor(*_MARKER_PEN), _MARKER_PEN_WIDTH_PX))
    painter.setBrush(QBrush(QColor(*color)))
    half = _MARKER_SIZE_PX / 2
    if square:
        painter.drawRect(QRectF(centre.x() - half, centre.y() - half, _MARKER_SIZE_PX, _MARKER_SIZE_PX))
    else:
        painter.drawEllipse(centre, half, half)


def _draw_attribution(painter: QPainter, rect: QRectF, text: str) -> None:
    """Credit the tile source in the map's bottom-right corner, as tile servers require."""
    font = QFont()
    font.setPixelSize(_ATTRIBUTION_FONT_PX)
    metrics = QFontMetrics(font)
    width = metrics.horizontalAdvance(text) + 2 * _ATTRIBUTION_PADDING_PX
    height = metrics.height() + 2 * _ATTRIBUTION_PADDING_PX
    box = QRectF(rect.right() - width, rect.bottom() - height, width, height)
    painter.fillRect(box, QColor(*_ATTRIBUTION_BACKGROUND))
    painter.setFont(font)
    painter.setPen(QColor(*_ATTRIBUTION_TEXT))
    painter.drawText(box, Qt.AlignmentFlag.AlignCenter, text)

from __future__ import annotations

import math
import os

import numpy as np
import pytest

from opencycletrainer.core.course_model import Course, CoursePoint
from opencycletrainer.ui.course_map import (
    DEFAULT_FOLLOW_ZOOM,
    MAX_FOLLOW_ZOOM,
    MIN_FOLLOW_ZOOM,
    CourseMapPanel,
    CourseMapWidget,
    mercator_xy,
)

_EARTH_RADIUS_M = 6_378_137.0


def _qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


# An L-shaped route: 4 legs north, then 4 legs east, each leg 100 m along the course.
_ROUTE = [(45.000 + 0.001 * i, 7.000) for i in range(5)] + [
    (45.004, 7.000 + 0.0014 * i) for i in range(1, 5)
]


def _course() -> Course:
    return Course(
        name="Map Course",
        points=tuple(
            CoursePoint(
                distance_m=100.0 * index, elevation_m=100.0, latitude_deg=lat, longitude_deg=lon
            )
            for index, (lat, lon) in enumerate(_ROUTE)
        ),
    )


def _xy(lat: float, lon: float) -> tuple[float, float]:
    return mercator_xy(lat, lon)


def _series(item) -> list[tuple[float, float]]:
    x, y = item.getData()
    if x is None:
        return []
    return list(zip(np.asarray(x, dtype=float), np.asarray(y, dtype=float)))


def _loaded(course: Course | None = None) -> CourseMapWidget:
    _qapp()
    widget = CourseMapWidget()
    widget.resize(400, 600)
    widget.load_course(course if course is not None else _course())
    return widget


def _view(widget: CourseMapWidget) -> tuple[tuple[float, float], tuple[float, float]]:
    (x_min, x_max), (y_min, y_max) = widget._plot.getViewBox().viewRange()
    return (x_min, x_max), (y_min, y_max)


def _centre(widget: CourseMapWidget) -> tuple[float, float]:
    (x_min, x_max), (y_min, y_max) = _view(widget)
    return (x_min + x_max) / 2.0, (y_min + y_max) / 2.0


def _width(widget: CourseMapWidget) -> float:
    (x_min, x_max), _ = _view(widget)
    return x_max - x_min


# ── Projection ────────────────────────────────────────────────────────────────

def test_mercator_puts_the_origin_at_zero():
    assert mercator_xy(0.0, 0.0) == pytest.approx((0.0, 0.0), abs=1e-6)


def test_mercator_matches_web_mercator_metres():
    x, y = mercator_xy(45.0, 7.0)

    assert x == pytest.approx(_EARTH_RADIUS_M * math.radians(7.0))
    assert y == pytest.approx(_EARTH_RADIUS_M * math.log(math.tan(math.pi / 4 + math.radians(45.0) / 2)))


# ── Route ─────────────────────────────────────────────────────────────────────

def test_a_new_course_is_all_still_to_ride():
    widget = _loaded()

    assert widget.has_route
    assert _series(widget._ahead_item) == pytest.approx([_xy(*point) for point in _ROUTE])
    assert _series(widget._ridden_item) == []


def test_the_route_splits_at_the_rider():
    widget = _loaded()

    widget.set_position(150.0)

    rider = _xy(45.0015, 7.0)
    ridden = _series(widget._ridden_item)
    ahead = _series(widget._ahead_item)
    assert ridden[0] == pytest.approx(_xy(*_ROUTE[0]))
    assert ridden[-1] == pytest.approx(rider)
    assert ahead[0] == pytest.approx(rider)
    assert ahead[-1] == pytest.approx(_xy(*_ROUTE[-1]))
    assert len(ridden) + len(ahead) == len(_ROUTE) + 2


def test_the_rider_dot_follows_the_position():
    widget = _loaded()
    assert _series(widget._dot) == pytest.approx([_xy(*_ROUTE[0])])

    widget.set_position(650.0)

    assert _series(widget._dot) == pytest.approx([_xy(45.004, 7.0035)])


def test_start_and_finish_are_marked():
    widget = _loaded()

    assert _series(widget._start_marker) == pytest.approx([_xy(*_ROUTE[0])])
    assert _series(widget._finish_marker) == pytest.approx([_xy(*_ROUTE[-1])])


def test_a_course_without_coordinates_has_no_route_to_draw():
    course = Course(
        name="No GPS",
        points=(CoursePoint(distance_m=0.0, elevation_m=1.0), CoursePoint(distance_m=10.0, elevation_m=2.0)),
    )

    widget = _loaded(course)

    assert not widget.has_route
    assert _series(widget._ahead_item) == []


def test_clearing_removes_the_route():
    widget = _loaded()

    widget.clear()

    assert not widget.has_route
    assert _series(widget._ahead_item) == []
    assert _series(widget._dot) == []


def test_a_lapped_course_shows_only_the_lap_being_ridden():
    lap_m = _course().total_distance_m
    widget = _loaded(_course().laps(3))

    widget.set_position(lap_m + 50.0)

    ridden = _series(widget._ridden_item)
    ahead = _series(widget._ahead_item)
    assert ridden == pytest.approx([_xy(*_ROUTE[0]), _xy(45.0005, 7.0)])
    assert ahead[-1] == pytest.approx(_xy(*_ROUTE[-1]))
    assert len(ridden) + len(ahead) == len(_ROUTE) + 2


# ── Follow and whole route ────────────────────────────────────────────────────

def test_the_map_follows_the_rider_by_default():
    widget = _loaded()

    widget.set_position(650.0)

    assert widget.following
    assert widget.zoom_level == DEFAULT_FOLLOW_ZOOM
    assert _centre(widget) == pytest.approx(_xy(45.004, 7.0035))


def test_zooming_in_halves_the_ground_shown_and_out_doubles_it():
    widget = _loaded()
    width = _width(widget)

    widget.zoom_in_button.click()
    assert widget.zoom_level == DEFAULT_FOLLOW_ZOOM + 1
    assert _width(widget) == pytest.approx(width / 2.0)

    widget.zoom_out_button.click()
    widget.zoom_out_button.click()
    assert _width(widget) == pytest.approx(width * 2.0)


def test_zoom_stops_at_its_limits():
    widget = _loaded()

    for _ in range(30):
        widget.zoom_in_button.click()
    assert widget.zoom_level == MAX_FOLLOW_ZOOM

    for _ in range(30):
        widget.zoom_out_button.click()
    assert widget.zoom_level == MIN_FOLLOW_ZOOM


def test_whole_route_shows_every_point_of_the_course():
    widget = _loaded()
    widget.set_position(650.0)

    widget.follow_button.click()

    assert not widget.following
    (x_min, x_max), (y_min, y_max) = _view(widget)
    for point in _ROUTE:
        x, y = _xy(*point)
        assert x_min <= x <= x_max
        assert y_min <= y <= y_max
    assert not widget.zoom_in_button.isEnabled()
    assert not widget.zoom_out_button.isEnabled()


def test_follow_returns_to_the_rider():
    widget = _loaded()
    widget.set_position(650.0)
    widget.follow_button.click()

    widget.follow_button.click()

    assert widget.following
    assert widget.zoom_in_button.isEnabled()
    assert _centre(widget) == pytest.approx(_xy(45.004, 7.0035))


def test_whole_route_view_does_not_move_with_the_rider():
    widget = _loaded()
    widget.follow_button.click()
    view = _view(widget)

    widget.set_position(650.0)

    (x_range, y_range) = _view(widget)
    assert x_range == pytest.approx(view[0])
    assert y_range == pytest.approx(view[1])


def test_map_follows_the_colour_theme():
    widget = _loaded()

    widget.apply_color_theme("dark")
    dark = widget._plot.backgroundBrush().color().getRgb()[:3]
    widget.apply_color_theme("light")
    light = widget._plot.backgroundBrush().color().getRgb()[:3]

    assert dark != light


# ── Panel ─────────────────────────────────────────────────────────────────────

def test_panel_starts_expanded_and_collapses_to_its_button():
    _qapp()
    panel = CourseMapPanel()
    panel.load_course(_course())

    assert not panel.collapsed
    assert panel.map_widget.isVisibleTo(panel)

    panel.collapse_button.click()

    assert panel.collapsed
    assert not panel.map_widget.isVisibleTo(panel)
    assert panel.collapse_button.isVisibleTo(panel)

    panel.collapse_button.click()

    assert not panel.collapsed
    assert panel.map_widget.isVisibleTo(panel)


# ── Workout screen ────────────────────────────────────────────────────────────

def _screen():
    _qapp()
    from opencycletrainer.storage.settings import AppSettings
    from opencycletrainer.ui.workout_screen import WorkoutScreen

    return WorkoutScreen(settings=AppSettings())


def test_map_panel_is_hidden_until_a_course_is_loaded():
    screen = _screen()

    assert not screen.course_map_panel.isVisibleTo(screen)


def test_loading_a_course_shows_the_map_beside_the_plots():
    screen = _screen()

    screen.load_course_chart(_course())

    assert screen.course_map_panel.isVisibleTo(screen)
    assert not screen.course_map_panel.collapsed


def test_a_course_without_coordinates_shows_no_map():
    screen = _screen()
    course = Course(
        name="No GPS",
        points=(CoursePoint(distance_m=0.0, elevation_m=1.0), CoursePoint(distance_m=10.0, elevation_m=2.0)),
    )

    screen.load_course_chart(course)

    assert not screen.course_map_panel.isVisibleTo(screen)


def test_course_position_moves_the_map_dot():
    screen = _screen()
    screen.load_course_chart(_course())

    screen.update_course_position(650.0)

    assert _series(screen.course_map_panel.map_widget._dot) == pytest.approx([_xy(45.004, 7.0035)])


def test_leaving_course_mode_hides_the_map():
    screen = _screen()
    screen.load_course_chart(_course())

    screen.set_course_mode(False)

    assert not screen.course_map_panel.isVisibleTo(screen)
    assert not screen.course_map_panel.map_widget.has_route

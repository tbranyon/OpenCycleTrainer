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

_screens: list = []


def _screen(settings=None):
    _qapp()
    from opencycletrainer.storage.settings import AppSettings
    from opencycletrainer.ui.workout_screen import WorkoutScreen

    screen = WorkoutScreen(settings=settings if settings is not None else AppSettings())
    _screens.append(screen)
    return screen


def _shown(screen):
    """Lay the screen out at a desktop size, so the map's width is real."""
    screen.resize(1200, 800)
    screen.show()
    _qapp().processEvents()
    return screen


@pytest.fixture(autouse=True)
def _destroy_screens():
    """Destroy workout screens after each test.

    Every live workout screen filters all application events for its hotkeys, so a
    screen left alive would slow down every test that runs afterwards.
    """
    yield
    from PySide6.QtCore import QCoreApplication, QEvent

    while _screens:
        _screens.pop().deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


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


def test_the_map_stays_hidden_when_turned_off_in_settings():
    from opencycletrainer.storage.settings import AppSettings

    screen = _screen(AppSettings(course_map_enabled=False))

    screen.load_course_chart(_course())

    assert not screen.course_map_panel.isVisibleTo(screen)
    assert not screen.course_map_panel.has_route


def test_turning_the_map_on_mid_ride_shows_the_rider_where_they_are():
    from opencycletrainer.storage.settings import AppSettings

    screen = _screen(AppSettings(course_map_enabled=False))
    screen.load_course_chart(_course())
    screen.update_course_position(650.0)

    screen.apply_settings(AppSettings(course_map_enabled=True))

    assert screen.course_map_panel.isVisibleTo(screen)
    assert _series(screen.course_map_panel.map_widget._dot) == pytest.approx([_xy(45.004, 7.0035)])


def test_turning_the_map_off_mid_ride_hides_it():
    from opencycletrainer.storage.settings import AppSettings

    screen = _screen()
    screen.load_course_chart(_course())

    screen.apply_settings(AppSettings(course_map_enabled=False))

    assert not screen.course_map_panel.isVisibleTo(screen)
    assert not screen.course_map_panel.has_route


def test_turning_the_map_on_outside_a_course_ride_shows_nothing():
    from opencycletrainer.storage.settings import AppSettings

    screen = _screen(AppSettings(course_map_enabled=False))
    screen.load_course_chart(_course())
    screen.set_course_mode(False)

    screen.apply_settings(AppSettings(course_map_enabled=True))

    assert not screen.course_map_panel.isVisibleTo(screen)


def test_the_map_uses_the_tile_source_chosen_in_settings():
    from opencycletrainer.storage.settings import AppSettings
    from opencycletrainer.ui.map_tiles import CYCLOSM, thunderforest_cycle

    screen = _screen(AppSettings(map_tile_source="cyclosm"))
    attribution = screen.course_map_panel.map_widget.attribution_label

    assert attribution.text() == CYCLOSM.attribution

    screen.apply_settings(
        AppSettings(map_tile_source="thunderforest_cycle", thunderforest_api_key="abc123")
    )

    assert attribution.text() == thunderforest_cycle("abc123").attribution


def test_the_map_opens_at_its_remembered_width():
    from opencycletrainer.storage.settings import AppSettings

    screen = _shown(_screen(AppSettings(course_map_width_px=300)))

    screen.load_course_chart(_course())
    _qapp().processEvents()

    assert screen.course_map_panel.width() == 300


def test_the_map_opens_collapsed_if_it_was_left_collapsed():
    from opencycletrainer.storage.settings import AppSettings

    screen = _screen(AppSettings(course_map_collapsed=True))

    screen.load_course_chart(_course())

    assert screen.course_map_panel.isVisibleTo(screen)
    assert screen.course_map_panel.collapsed


def test_the_map_keeps_the_width_the_rider_drags_it_to():
    screen = _shown(_screen())
    screen.load_course_chart(_course())
    _qapp().processEvents()
    splitter = screen.chart_splitter

    splitter.moveSplitter(splitter.width() - 350, 1)
    dragged_width = screen.course_map_panel.width()

    assert screen.course_map_layout() == (dragged_width, False)

    screen.course_map_panel.set_collapsed(True)
    _qapp().processEvents()

    assert screen.course_map_layout() == (dragged_width, True)
    assert screen.course_map_panel.width() < dragged_width

    screen.course_map_panel.set_collapsed(False)
    _qapp().processEvents()

    assert screen.course_map_panel.width() == dragged_width


# ── Map tiles ─────────────────────────────────────────────────────────────────

from PySide6.QtCore import QObject, Signal  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402

from opencycletrainer.ui.map_tiles import (  # noqa: E402
    CYCLOSM,
    OPENSTREETMAP,
    tile_bounds,
    tile_zoom_for,
    visible_tiles,
)


class _FakeTiles(QObject):
    """Records which tiles the map wants and hands over tiles when the test says so."""

    tile_ready = Signal(int, int, int)

    def __init__(self, source=OPENSTREETMAP) -> None:
        super().__init__()
        self.source = source
        self.wanted: list[tuple[int, int, int]] = []
        self._images: dict[tuple[int, int, int], QImage] = {}

    def set_wanted(self, tiles) -> None:
        self.wanted = list(tiles)

    def image(self, key):
        return self._images.get(key)

    def deliver(self, key) -> None:
        image = QImage(256, 256, QImage.Format.Format_RGB32)
        image.fill(0x336699)
        self._images[key] = image
        self.tile_ready.emit(*key)


def _tiled(course: Course | None = None) -> tuple[CourseMapWidget, _FakeTiles]:
    _qapp()
    tiles = _FakeTiles()
    widget = CourseMapWidget(tile_provider=tiles)
    widget.resize(400, 600)
    widget.load_course(course if course is not None else _course())
    return widget, tiles


def _view_rect(widget: CourseMapWidget) -> tuple[float, float, float, float]:
    (x_min, x_max), (y_min, y_max) = _view(widget)
    return x_min, x_max, y_min, y_max


def test_following_asks_for_the_tiles_in_view_at_the_follow_zoom():
    widget, tiles = _tiled()

    widget.set_position(650.0)

    assert tiles.wanted
    assert set(tiles.wanted) == set(visible_tiles(_view_rect(widget), widget.zoom_level))


def test_zooming_asks_for_tiles_at_the_new_zoom():
    widget, tiles = _tiled()

    widget.zoom_in_button.click()

    assert {key[0] for key in tiles.wanted} == {DEFAULT_FOLLOW_ZOOM + 1}


def test_whole_route_asks_for_tiles_matched_to_the_screen():
    widget, tiles = _tiled()

    widget.follow_button.click()

    x_min, x_max, _, _ = _view_rect(widget)
    width_px, _ = widget._view_size_px()
    zoom = tile_zoom_for((x_max - x_min) / width_px, max_zoom=OPENSTREETMAP.max_zoom)
    assert {key[0] for key in tiles.wanted} == {zoom}


def test_a_delivered_tile_is_drawn_under_the_route_at_its_place():
    widget, tiles = _tiled()
    key = tiles.wanted[0]

    tiles.deliver(key)

    item = widget._tile_items[key]
    rect = item.mapRectToParent(item.boundingRect())
    x0, y0, x1, y1 = tile_bounds(*key)
    assert (rect.left(), rect.top(), rect.right(), rect.bottom()) == pytest.approx((x0, y0, x1, y1), rel=1e-9)
    assert item.zValue() < widget._ahead_item.zValue()


def test_tiles_already_held_are_drawn_straight_away():
    widget, tiles = _tiled()
    key = tiles.wanted[0]
    tiles.deliver(key)

    widget.load_course(_course())

    assert key in widget._tile_items


def test_a_tile_that_arrives_after_the_view_moved_on_is_not_drawn():
    widget, tiles = _tiled()
    old_key = tiles.wanted[0]
    widget.zoom_in_button.click()

    tiles.deliver(old_key)

    assert old_key not in widget._tile_items


def test_tiles_that_leave_the_view_are_removed():
    widget, tiles = _tiled()
    for key in list(tiles.wanted):
        tiles.deliver(key)
    drawn = set(widget._tile_items)

    widget.zoom_out_button.click()

    assert not drawn & set(widget._tile_items)


def test_the_map_credits_its_tile_source():
    widget, _ = _tiled()

    assert widget.attribution_label.text() == "© OpenStreetMap contributors"
    assert widget.attribution_label.isVisibleTo(widget)


def test_clearing_the_map_stops_asking_for_tiles_and_drops_them():
    widget, tiles = _tiled()
    tiles.deliver(tiles.wanted[0])

    widget.clear()

    assert tiles.wanted == []
    assert widget._tile_items == {}


def test_a_course_without_coordinates_asks_for_no_tiles():
    _qapp()
    tiles = _FakeTiles()
    widget = CourseMapWidget(tile_provider=tiles)
    course = Course(
        name="No GPS",
        points=(CoursePoint(distance_m=0.0, elevation_m=1.0), CoursePoint(distance_m=10.0, elevation_m=2.0)),
    )

    widget.load_course(course)

    assert tiles.wanted == []


def test_switching_tile_source_redraws_the_map_from_the_new_server(monkeypatch):
    from opencycletrainer.ui import map_tiles

    widget, old_tiles = _tiled()
    shown = list(old_tiles.wanted)
    old_tiles.deliver(shown[0])
    created: list[_FakeTiles] = []

    def _create(source):
        created.append(_FakeTiles(source))
        return created[-1]

    monkeypatch.setattr(map_tiles, "create_tile_provider", _create)

    widget.set_tile_source(CYCLOSM)

    (new_tiles,) = created
    assert widget.attribution_label.text() == CYCLOSM.attribution
    assert widget._tile_items == {}
    assert old_tiles.wanted == []
    assert new_tiles.wanted == shown

    old_tiles.deliver(shown[1])
    assert widget._tile_items == {}

    widget.set_tile_source(CYCLOSM)
    assert len(created) == 1

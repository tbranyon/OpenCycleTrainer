"""The saved workout chart is redrawn off-screen at a fixed, shareable size."""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

from opencycletrainer.core.workout_model import Workout, WorkoutInterval

_POWER_GREEN = (34, 197, 94)
_ALPHA1_VIOLET = (168, 85, 247)
_DARK_BACKGROUND = (15, 23, 42)
_LIGHT_BACKGROUND = (255, 255, 255)
_COLOUR_TOLERANCE = 12
_HEADER_FRACTION = 0.2   # title and legend live in the top of the image
_FILLED_FRACTION = 0.9   # a trace "fills" the axis when it reaches this far right


def _qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _workout() -> Workout:
    """Two flat intervals: 5 min at 100 W, then 10 min at 180 W."""
    return Workout(
        name="Sweet Spot",
        ftp_watts=200,
        intervals=(
            WorkoutInterval(0, 300, 50.0, 50.0, 100, 100),
            WorkoutInterval(300, 600, 90.0, 90.0, 180, 180),
        ),
    )


def _series(seconds: int, value: int) -> list[tuple[float, int]]:
    return [(float(t), value) for t in range(seconds + 1)]


def _free_ride_widget(seconds: int = 600, *, alpha1: bool = False):
    from opencycletrainer.ui.workout_chart import WorkoutChartWidget

    _qapp()
    widget = WorkoutChartWidget()
    widget.resize(500, 300)
    widget.set_dfa_alpha1_enabled(alpha1)
    widget.load_free_ride()
    alpha1_series = [(float(t), 0.9) for t in range(120, seconds + 1, 5)] if alpha1 else None
    widget.update_free_ride_charts(
        float(seconds), _series(seconds, 210), _series(seconds, 140), None, alpha1_series,
    )
    return widget


def _pixels(path: Path) -> np.ndarray:
    """Return the saved image as a height × width × 3 RGB array."""
    from PySide6.QtGui import QImage

    image = QImage(str(path)).convertToFormat(QImage.Format.Format_RGB888)
    assert not image.isNull()
    rows = np.frombuffer(image.constBits(), dtype=np.uint8).reshape(image.height(), image.bytesPerLine())
    return rows[:, : image.width() * 3].reshape(image.height(), image.width(), 3).copy()


def _columns_with(pixels: np.ndarray, rgb: tuple[int, int, int]) -> np.ndarray:
    """Columns holding the given trace colour, ignoring the header (title and legend)."""
    body = pixels[int(pixels.shape[0] * _HEADER_FRACTION):].astype(int)
    close = (np.abs(body - np.array(rgb)) <= _COLOUR_TOLERANCE).all(axis=2)
    return np.flatnonzero(close.any(axis=0))


def test_export_has_a_fixed_shareable_size_whatever_the_window_size(tmp_path):
    from opencycletrainer.ui.chart_export import EXPORT_HEIGHT, EXPORT_WIDTH

    widget = _free_ride_widget()

    path = widget.export_image(tmp_path / "ride.png")

    pixels = _pixels(path)
    assert pixels.shape[:2] == (EXPORT_HEIGHT, EXPORT_WIDTH)
    assert EXPORT_WIDTH / EXPORT_HEIGHT == pytest.approx(4 / 3)
    assert EXPORT_WIDTH >= 1600


def test_free_ride_export_fills_the_x_axis(tmp_path):
    widget = _free_ride_widget(seconds=600)  # ten minutes inside a thirty-minute window

    pixels = _pixels(widget.export_image(tmp_path / "ride.png"))

    assert _columns_with(pixels, _POWER_GREEN).max() >= pixels.shape[1] * _FILLED_FRACTION


def test_workout_stopped_early_fills_the_x_axis(tmp_path):
    from opencycletrainer.ui.workout_chart import WorkoutChartWidget

    _qapp()
    widget = WorkoutChartWidget()
    widget.load_workout(_workout(), ftp_watts=200)
    widget.update_charts(300.0, 0, _series(300, 105), _series(300, 130))  # stopped a third in

    pixels = _pixels(widget.export_image(tmp_path / "ride.png"))

    assert _columns_with(pixels, _POWER_GREEN).max() >= pixels.shape[1] * _FILLED_FRACTION


def test_export_leaves_the_live_chart_as_it_was(tmp_path):
    widget = _free_ride_widget(seconds=600)
    x_range_before = widget._workout_plot.getViewBox().viewRange()[0]
    size_before = widget.size()

    widget.export_image(tmp_path / "ride.png")

    assert widget._workout_plot.getViewBox().viewRange()[0] == x_range_before
    assert widget.size() == size_before


def test_export_leaves_no_windows_behind(tmp_path):
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication
    from shiboken6 import getCppPointer, isValid

    def open_windows() -> dict[int, str]:
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        return {
            getCppPointer(w)[0]: type(w).__name__
            for w in QApplication.topLevelWidgets() if isValid(w)
        }

    widget = _free_ride_widget()
    before = open_windows()

    widget.export_image(tmp_path / "ride.png")
    widget.export_image(tmp_path / "again.png")

    assert [name for key, name in open_windows().items() if key not in before] == []


def test_export_before_any_samples_still_writes_an_image(tmp_path):
    from opencycletrainer.ui.chart_export import EXPORT_HEIGHT, EXPORT_WIDTH
    from opencycletrainer.ui.workout_chart import WorkoutChartWidget

    _qapp()
    widget = WorkoutChartWidget()
    widget.load_free_ride()

    pixels = _pixels(widget.export_image(tmp_path / "ride.png"))

    assert pixels.shape[:2] == (EXPORT_HEIGHT, EXPORT_WIDTH)
    assert _columns_with(pixels, _POWER_GREEN).size == 0


def test_export_follows_the_app_colour_theme(tmp_path):
    widget = _free_ride_widget()

    light = _pixels(widget.export_image(tmp_path / "light.png"))
    widget.apply_color_theme("dark")
    dark = _pixels(widget.export_image(tmp_path / "dark.png"))

    assert tuple(light[0, 0]) == _LIGHT_BACKGROUND
    assert tuple(dark[0, 0]) == _DARK_BACKGROUND


def test_alpha1_trace_is_exported_only_when_the_overlay_is_on(tmp_path):
    with_alpha1 = _pixels(_free_ride_widget(alpha1=True).export_image(tmp_path / "a1.png"))
    without = _pixels(_free_ride_widget(alpha1=False).export_image(tmp_path / "plain.png"))

    assert _columns_with(with_alpha1, _ALPHA1_VIOLET).size > 0
    assert _columns_with(without, _ALPHA1_VIOLET).size == 0


def test_export_creates_the_destination_folder(tmp_path):
    widget = _free_ride_widget()

    path = widget.export_image(tmp_path / "png" / "ride.png")

    assert path.is_file()


@pytest.mark.parametrize(
    ("span_seconds", "expected_step"),
    [(600, 120), (1800, 300), (3600, 600), (3 * 3600, 1800), (45, 10)],
)
def test_time_axis_uses_round_tick_steps(span_seconds, expected_step):
    from opencycletrainer.ui.chart_export import time_tick_step

    assert time_tick_step(float(span_seconds)) == expected_step


@pytest.mark.parametrize(
    ("seconds", "span_seconds", "label"),
    [(90, 600, "1:30"), (600, 1800, "10:00"), (5400, 3 * 3600, "1:30:00"), (0, 3 * 3600, "0:00:00")],
)
def test_time_axis_labels_show_hours_only_on_long_rides(seconds, span_seconds, label):
    from opencycletrainer.ui.chart_export import format_axis_time

    assert format_axis_time(float(seconds), float(span_seconds)) == label


def _noisy_power(seconds: int) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(5)
    t = np.arange(1, seconds + 1, dtype=float)
    return t, 200.0 + rng.normal(0.0, 15.0, seconds)


def test_long_ride_power_is_smoothed_to_what_the_image_can_show():
    from opencycletrainer.ui.chart_export import EXPORT_WIDTH, smooth_for_width

    t, watts = _noisy_power(3 * 3600)

    smooth_t, smooth_watts = smooth_for_width((t, watts), float(t[-1]), EXPORT_WIDTH)

    assert len(smooth_t) < len(t)
    assert np.nanstd(smooth_watts) < np.std(watts) / 2
    assert np.nanmean(smooth_watts) == pytest.approx(watts.mean(), abs=1.0)
    assert smooth_t[0] == t[0] and smooth_t[-1] > t[-1] * 0.99


def test_short_ride_power_is_left_as_recorded():
    from opencycletrainer.ui.chart_export import EXPORT_WIDTH, smooth_for_width

    t, watts = _noisy_power(300)

    smooth_t, smooth_watts = smooth_for_width((t, watts), float(t[-1]), EXPORT_WIDTH)

    assert np.array_equal(smooth_t, t)
    assert np.array_equal(smooth_watts, watts)


def test_smoothing_keeps_dropouts_as_gaps():
    from opencycletrainer.ui.chart_export import EXPORT_WIDTH, smooth_for_width

    t, watts = _noisy_power(3 * 3600)
    watts[4000:4600] = np.nan

    smooth_t, smooth_watts = smooth_for_width((t, watts), float(t[-1]), EXPORT_WIDTH)

    inside_gap = (smooth_t > 4100) & (smooth_t < 4500)
    assert inside_gap.any()
    assert np.isnan(smooth_watts[inside_gap]).all()
    assert np.isfinite(smooth_watts[~((smooth_t > 3990) & (smooth_t < 4610))]).all()


# ── Course map ────────────────────────────────────────────────────────────────

_ROUTE_RED = (220, 38, 38)
_TILE_MAGENTA = (255, 0, 255)
_MAP_LEFT_FRACTION = 0.615  # on course rides the map takes the right part of the image
_WAIT_SECONDS = 2.0
_CREDIT_TEXT = (30, 41, 59)
_CREDIT_BAND_PX = 40


def _has_colour(pixels: np.ndarray, rgb: tuple[int, int, int]) -> bool:
    return bool((np.abs(pixels.astype(int) - np.array(rgb)) <= _COLOUR_TOLERANCE).all(axis=-1).any())

# An L-shaped route: 4 legs north, then 4 legs east, each leg 100 m along the course.
_ROUTE = [(45.000 + 0.001 * i, 7.000) for i in range(5)] + [
    (45.004, 7.000 + 0.0014 * i) for i in range(1, 5)
]


def _course():
    from opencycletrainer.core.course_model import Course, CoursePoint

    return Course(
        name="Map Course",
        points=tuple(
            CoursePoint(distance_m=100.0 * i, elevation_m=100.0, latitude_deg=lat, longitude_deg=lon)
            for i, (lat, lon) in enumerate(_ROUTE)
        ),
    )


def _course_map():
    """The L route ridden as far as its corner."""
    from opencycletrainer.ui.course_map import mercator_xy
    from opencycletrainer.ui.map_export import CourseMapExportData
    from opencycletrainer.ui.map_tiles import OPENSTREETMAP

    xs, ys = (np.array(axis, dtype=float) for axis in zip(*(mercator_xy(*p) for p in _ROUTE)))
    return CourseMapExportData(
        ridden=(xs[:5], ys[:5]),
        ahead=(xs[4:], ys[4:]),
        start=(xs[0], ys[0]),
        finish=(xs[-1], ys[-1]),
        rider=(xs[4], ys[4]),
        tile_source=OPENSTREETMAP,
    )


def _ride(course_map=None):
    from opencycletrainer.ui.chart_export import ChartExportData

    t = np.arange(0.0, 601.0)
    empty = (np.array([]), np.array([]))
    return ChartExportData(
        title="Course", power=(t, np.full(len(t), 210.0)), heart_rate=empty, target=empty,
        course_map=course_map,
    )


def _tile_image():
    from PySide6.QtGui import QColor, QImage

    image = QImage(256, 256, QImage.Format.Format_RGB32)
    image.fill(QColor(*_TILE_MAGENTA))
    return image


class _Tiles:
    """A tile provider that hands over tiles when the test says so (or holds them all)."""

    def __init__(self, source=None, *, hold_all: bool = False) -> None:
        from PySide6.QtCore import QObject, Signal

        class _Signals(QObject):
            tile_ready = Signal(int, int, int)

        self._signals = _Signals()
        self.tile_ready = self._signals.tile_ready
        self.source = source
        self.wanted: list[tuple[int, int, int]] = []
        self.asked = False
        self._hold_all = hold_all
        self._images: dict = {}

    def set_wanted(self, tiles) -> None:
        self.asked = self.asked or bool(tiles)
        self.wanted = list(tiles)

    def image(self, key):
        return _tile_image() if self._hold_all else self._images.get(key)

    def deliver(self, key) -> None:
        self._images[key] = _tile_image()
        self.tile_ready.emit(*key)


def _wait_until(predicate) -> bool:
    import time

    from PySide6.QtCore import QCoreApplication

    deadline = time.monotonic() + _WAIT_SECONDS
    while time.monotonic() < deadline:
        QCoreApplication.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def test_course_ride_image_draws_the_route_map_right_of_the_chart(tmp_path):
    from opencycletrainer.ui.chart_export import save_chart_image

    _qapp()
    pixels = _pixels(save_chart_image(_ride(_course_map()), tmp_path / "ride.png"))

    map_left = pixels.shape[1] * _MAP_LEFT_FRACTION
    route_ahead = _columns_with(pixels, _ROUTE_RED)
    assert route_ahead.size and route_ahead.min() >= map_left
    assert (_columns_with(pixels, _POWER_GREEN) >= map_left).any()  # the ridden road
    power = _columns_with(pixels, _POWER_GREEN)
    assert power[power < map_left].max() >= pixels.shape[1] * 0.5  # the chart fills its share


def test_map_tiles_are_drawn_beneath_the_route(tmp_path):
    from opencycletrainer.ui.chart_export import save_chart_image

    _qapp()
    tiled = _pixels(save_chart_image(
        _ride(_course_map()), tmp_path / "tiled.png", tile_image=lambda _key: _tile_image(),
    ))
    plain = _pixels(save_chart_image(_ride(_course_map()), tmp_path / "plain.png"))

    tile_columns = _columns_with(tiled, _TILE_MAGENTA)
    assert tile_columns.size and tile_columns.min() >= tiled.shape[1] * _MAP_LEFT_FRACTION
    assert _columns_with(tiled, _ROUTE_RED).size
    assert _columns_with(plain, _TILE_MAGENTA).size == 0

    # The tile source is credited along the map's bottom edge, only where its tiles are drawn.
    magenta = (np.abs(tiled.astype(int) - np.array(_TILE_MAGENTA)) <= _COLOUR_TOLERANCE).all(axis=2)
    map_bottom = int(np.flatnonzero(magenta.any(axis=1)).max())
    credit_band = (slice(map_bottom - _CREDIT_BAND_PX, map_bottom + 1), slice(int(tile_columns.min()), None))
    assert _has_colour(tiled[credit_band], _CREDIT_TEXT)
    assert not _has_colour(plain[credit_band], _CREDIT_TEXT)


def test_course_ride_image_is_saved_once_its_map_tiles_arrive(tmp_path):
    from opencycletrainer.ui.chart_export import ChartImageExport

    _qapp()
    tiles = _Tiles()
    path = tmp_path / "ride.png"
    export = ChartImageExport(_ride(_course_map()), path, tile_provider=tiles)
    saved = []
    export.finished.connect(saved.append)

    export.start()

    assert tiles.wanted and len({zoom for zoom, _, _ in tiles.wanted}) == 1
    assert not path.exists()
    for key in list(tiles.wanted):
        tiles.deliver(key)
    assert saved == [path]
    assert _columns_with(_pixels(path), _TILE_MAGENTA).size
    assert tiles.wanted == []


@pytest.mark.parametrize("course_map", [True, False], ids=["tiles-at-hand", "no-map"])
def test_ride_image_is_saved_straight_away_when_there_is_nothing_to_wait_for(tmp_path, course_map):
    from opencycletrainer.ui.chart_export import ChartImageExport

    _qapp()
    tiles = _Tiles(hold_all=True)
    path = tmp_path / "ride.png"
    export = ChartImageExport(_ride(_course_map() if course_map else None), path, tile_provider=tiles)

    export.start()

    assert path.is_file()
    assert (_columns_with(_pixels(path), _TILE_MAGENTA).size > 0) is course_map
    assert tiles.wanted == []


def test_missing_tiles_stop_holding_up_the_image_after_a_short_wait(tmp_path):
    from opencycletrainer.ui.chart_export import ChartImageExport

    _qapp()
    tiles = _Tiles()
    path = tmp_path / "ride.png"
    export = ChartImageExport(_ride(_course_map()), path, tile_provider=tiles, wait_seconds=0.05)
    export.start()
    tiles.deliver(tiles.wanted[len(tiles.wanted) // 2])  # one from the middle of the map

    assert not path.exists()
    assert _wait_until(path.exists)
    assert _columns_with(_pixels(path), _TILE_MAGENTA).size
    assert tiles.wanted == []


def test_finishing_now_saves_the_image_with_the_tiles_at_hand(tmp_path):
    from opencycletrainer.ui.chart_export import ChartImageExport

    _qapp()
    tiles = _Tiles()
    path = tmp_path / "ride.png"
    export = ChartImageExport(_ride(_course_map()), path, tile_provider=tiles)
    saved = []
    export.finished.connect(saved.append)
    export.start()

    export.finish_now()
    export.finish_now()

    assert saved == [path] and path.is_file()


def _course_screen(monkeypatch, settings=None, *, tiles_at_hand=True):
    from opencycletrainer.storage.settings import AppSettings
    from opencycletrainer.ui import map_tiles
    from opencycletrainer.ui.workout_screen import WorkoutScreen

    _qapp()
    if tiles_at_hand:
        monkeypatch.setattr(map_tiles, "create_tile_provider", lambda source: _Tiles(source, hold_all=True))
    screen = WorkoutScreen(settings=settings if settings is not None else AppSettings())
    screen.load_course_chart(_course())
    screen.update_course_position(400.0)
    return screen


def test_course_ride_image_shows_the_map_with_the_road_ridden(monkeypatch, tmp_path):
    screen = _course_screen(monkeypatch)

    pixels = _pixels(screen.export_chart_image(tmp_path / "ride.png", "Course"))

    map_left = pixels.shape[1] * _MAP_LEFT_FRACTION
    assert _columns_with(pixels, _TILE_MAGENTA).min() >= map_left
    assert (_columns_with(pixels, _POWER_GREEN) >= map_left).any()
    assert (_columns_with(pixels, _ROUTE_RED) >= map_left).any()


def test_ride_image_has_no_map_when_the_map_is_turned_off(monkeypatch, tmp_path):
    from opencycletrainer.storage.settings import AppSettings

    screen = _course_screen(monkeypatch, AppSettings(course_map_enabled=False))

    pixels = _pixels(screen.export_chart_image(tmp_path / "ride.png", "Course"))

    assert _columns_with(pixels, _TILE_MAGENTA).size == 0
    assert _columns_with(pixels, _ROUTE_RED).size == 0


def test_screen_saves_a_ride_image_still_waiting_for_tiles_when_asked_to_finish(monkeypatch, tmp_path):
    screen = _course_screen(monkeypatch, tiles_at_hand=False)

    path = screen.export_chart_image(tmp_path / "ride.png", "Course")
    assert not path.exists()
    screen.finish_chart_exports()

    assert path.is_file()


def test_a_ride_after_a_course_ride_saves_its_image_without_that_map(monkeypatch, tmp_path):
    screen = _course_screen(monkeypatch)
    screen.set_course_mode(False)
    kept = _pixels(screen.export_chart_image(tmp_path / "course.png", "Course"))

    screen.load_free_ride_chart()
    later = _pixels(screen.export_chart_image(tmp_path / "free.png", "Free ride"))

    assert _columns_with(kept, _TILE_MAGENTA).size
    assert _columns_with(later, _TILE_MAGENTA).size == 0

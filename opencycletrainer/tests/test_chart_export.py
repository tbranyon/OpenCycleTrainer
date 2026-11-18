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

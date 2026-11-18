from __future__ import annotations

import os

import numpy as np
import pytest

from opencycletrainer.core.course_model import Course, CoursePoint
from opencycletrainer.ui.workout_chart import WorkoutChartWidget, course_grade_band


def _qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _course() -> Course:
    profile = ((0.0, 100.0), (1000.0, 100.0), (2000.0, 180.0), (3000.0, 60.0))
    return Course(
        name="Chart Course",
        points=tuple(CoursePoint(distance_m=d, elevation_m=e) for d, e in profile),
    )


def test_course_plot_is_hidden_until_a_course_is_loaded():
    _qapp()
    widget = WorkoutChartWidget()

    assert not widget.course_plot_shown


def test_course_plot_is_only_built_when_a_course_is_loaded():
    _qapp()
    widget = WorkoutChartWidget()
    plots_without_course = widget.layout().count()

    widget.load_course(_course())

    assert widget.layout().count() == plots_without_course + 1


def test_reloading_a_course_reuses_the_course_plot():
    _qapp()
    widget = WorkoutChartWidget()
    widget.load_course(_course())
    plots_with_course = widget.layout().count()

    widget.clear_course()
    widget.load_course(_course())

    assert widget.layout().count() == plots_with_course
    assert widget.course_plot_shown


def test_position_updates_are_ignored_without_a_course():
    _qapp()
    widget = WorkoutChartWidget()

    widget.set_course_position(500.0)

    assert widget.course_position_m == 0.0


def test_loading_a_course_shows_its_elevation_profile():
    _qapp()
    widget = WorkoutChartWidget()

    widget.load_course(_course())

    distances, elevations = widget._course_profile.getOriginalDataset()
    assert widget.course_plot_shown
    assert list(distances) == [0.0, 1000.0, 2000.0, 3000.0]
    assert list(elevations) == [100.0, 100.0, 180.0, 60.0]


def test_course_plot_replaces_the_interval_plot():
    _qapp()
    widget = WorkoutChartWidget()

    widget.load_course(_course())

    assert widget._interval_plot.isHidden()
    assert not widget._workout_plot.isHidden()


def test_course_plot_spans_the_whole_course():
    _qapp()
    widget = WorkoutChartWidget()

    widget.load_course(_course())

    (x_min, x_max), (y_min, y_max) = widget._course_plot.getViewBox().viewRange()
    assert x_min == pytest.approx(0.0)
    assert x_max == pytest.approx(3000.0)
    assert y_min <= 60.0
    assert y_max >= 180.0


def test_position_marker_starts_at_the_course_start_and_follows_updates():
    _qapp()
    widget = WorkoutChartWidget()
    widget.load_course(_course())

    assert widget.course_position_m == 0.0

    widget.set_course_position(1234.5)

    assert widget.course_position_m == pytest.approx(1234.5)


def test_ridden_part_of_the_profile_is_highlighted():
    _qapp()
    widget = WorkoutChartWidget()
    widget.load_course(_course())

    widget.set_course_position(1500.0)

    distances, elevations = widget._course_ridden.getOriginalDataset()
    assert list(distances) == [0.0, 1000.0, 1500.0]
    assert list(elevations) == pytest.approx([100.0, 100.0, 140.0])


def test_interval_plot_stays_hidden_while_a_course_is_shown():
    _qapp()
    widget = WorkoutChartWidget()
    widget.load_course(_course())

    widget.set_interval_plot_visible(True)

    assert widget._interval_plot.isHidden()


def test_clearing_the_course_hides_its_plot():
    _qapp()
    widget = WorkoutChartWidget()
    widget.load_course(_course())

    widget.clear_course()
    widget.set_interval_plot_visible(True)

    assert not widget.course_plot_shown
    assert not widget._interval_plot.isHidden()


def test_course_ride_still_plots_live_power_against_time():
    _qapp()
    widget = WorkoutChartWidget()
    widget.load_course(_course())

    widget.update_free_ride_charts(3.0, [(1.0, 150), (2.0, 160)], [])

    times, watts = widget._workout_actual.getOriginalDataset()
    assert list(times) == [1.0, 2.0]
    assert list(watts) == [150.0, 160.0]


def test_course_plot_follows_the_colour_theme():
    _qapp()
    widget = WorkoutChartWidget()
    widget.load_course(_course())

    widget.apply_color_theme("dark")
    dark = widget._course_plot.backgroundBrush().color().getRgb()[:3]
    widget.apply_color_theme("light")
    light = widget._course_plot.backgroundBrush().color().getRgb()[:3]

    assert dark != light
    assert light == widget._workout_plot.backgroundBrush().color().getRgb()[:3]


def _axis_labels(widget: WorkoutChartWidget, axis_name: str, values: list[float]) -> list[str]:
    """Tick labels the course plot's axis would draw at *values* (given in metres)."""
    axis = widget._course_plot.getAxis(axis_name)
    return axis.tickStrings(values, axis.scale, 1.0)


def test_course_axes_are_metric_by_default():
    _qapp()
    widget = WorkoutChartWidget()
    widget.load_course(_course())

    assert widget._course_plot.getAxis("bottom").labelText == "km"
    assert widget._course_plot.getAxis("left").labelText == "m"
    assert [float(label) for label in _axis_labels(widget, "bottom", [0.0, 2500.0])] == [0.0, 2.5]
    assert [float(label) for label in _axis_labels(widget, "left", [100.0, 200.0])] == [100.0, 200.0]


def test_course_axes_show_miles_and_feet_for_imperial_units():
    _qapp()
    widget = WorkoutChartWidget()
    widget.set_display_units("imperial")
    widget.load_course(_course())

    assert widget._course_plot.getAxis("bottom").labelText == "mi"
    assert widget._course_plot.getAxis("left").labelText == "ft"
    assert [float(label) for label in _axis_labels(widget, "bottom", [0.0, 1609.344])] == [0.0, 1.0]
    assert [float(label) for label in _axis_labels(widget, "left", [0.0, 304.8])] == [0.0, 1000.0]


def test_changing_units_relabels_a_course_already_shown():
    _qapp()
    widget = WorkoutChartWidget()
    widget.load_course(_course())
    widget.set_course_position(1500.0)

    widget.set_display_units("imperial")

    assert widget._course_plot.getAxis("bottom").labelText == "mi"
    assert widget._course_plot.getAxis("left").labelText == "ft"
    assert widget.course_position_m == pytest.approx(1500.0)
    (x_min, x_max), _ = widget._course_plot.getViewBox().viewRange()
    assert (x_min, x_max) == pytest.approx((0.0, 3000.0))

    widget.set_display_units("metric")

    assert widget._course_plot.getAxis("bottom").labelText == "km"


def test_units_can_be_set_before_any_course_is_loaded():
    _qapp()
    widget = WorkoutChartWidget()

    widget.set_display_units("imperial")

    assert not widget.course_plot_shown


# ── Zoomed view ───────────────────────────────────────────────────────────────

_METERS_PER_MILE = 1609.344


def _long_course() -> Course:
    """A 5 km course sampled every 50 m: 2 km flat at 100 m, then a steady +5 % climb."""
    points = []
    for index in range(101):
        distance = index * 50.0
        elevation = 100.0 if distance <= 2000.0 else 100.0 + (distance - 2000.0) * 0.05
        points.append(CoursePoint(distance_m=distance, elevation_m=elevation))
    return Course(name="Long Course", points=tuple(points))


def _x_range(widget: WorkoutChartWidget) -> tuple[float, float]:
    (x_min, x_max), _ = widget._course_plot.getViewBox().viewRange()
    return x_min, x_max


def _y_range(widget: WorkoutChartWidget) -> tuple[float, float]:
    _, (y_min, y_max) = widget._course_plot.getViewBox().viewRange()
    return y_min, y_max


def _zoomed(units: str = "metric") -> WorkoutChartWidget:
    _qapp()
    widget = WorkoutChartWidget()
    widget.set_display_units(units)
    widget.load_course(_long_course())
    widget.course_zoom_button.click()
    return widget


def test_course_starts_in_the_full_view_with_a_zoom_button():
    _qapp()
    widget = WorkoutChartWidget()

    widget.load_course(_long_course())

    assert not widget.course_zoomed
    assert widget.course_zoom_button.isVisibleTo(widget._course_plot)
    assert _x_range(widget) == pytest.approx((0.0, 5000.0))


def test_zoomed_view_shows_one_kilometre_from_the_rider_by_default():
    widget = _zoomed()

    assert widget.course_zoomed
    assert _x_range(widget) == pytest.approx((0.0, 1000.0))


def test_zoomed_view_shows_one_mile_with_imperial_units():
    widget = _zoomed(units="imperial")

    assert _x_range(widget) == pytest.approx((0.0, _METERS_PER_MILE))


def test_zoom_span_is_configurable():
    widget = _zoomed()

    widget.set_course_zoom_span(2.5)

    assert _x_range(widget) == pytest.approx((0.0, 2500.0))


def test_zoomed_view_holds_still_until_the_rider_nears_its_right_edge():
    widget = _zoomed()

    widget.set_course_position(940.0)

    assert _x_range(widget) == pytest.approx((0.0, 1000.0))


def test_zoomed_view_moves_the_rider_back_to_the_left_at_95_percent():
    widget = _zoomed()

    widget.set_course_position(950.0)

    assert _x_range(widget) == pytest.approx((950.0, 1950.0))

    widget.set_course_position(1800.0)

    assert _x_range(widget) == pytest.approx((950.0, 1950.0))


def test_zoomed_view_draws_the_road_in_full_detail():
    widget = _zoomed()

    distances, _ = widget._course_profile.getOriginalDataset()

    assert list(distances[:3]) == pytest.approx([0.0, 50.0, 100.0])


def test_zoomed_view_scales_elevation_to_the_road_in_view():
    widget = _zoomed()
    flat_low, flat_high = _y_range(widget)

    widget.set_course_position(3000.0)
    climb_low, climb_high = _y_range(widget)

    # Flat at 100 m in the first window; 150 m to 200 m in the window from 3 km.
    assert flat_low <= 100.0 <= flat_high
    assert flat_high - flat_low < 30.0
    assert climb_low <= 150.0 and climb_high >= 200.0
    assert climb_low > 120.0
    assert climb_high - climb_low < 100.0


def test_zoom_button_returns_to_the_full_view():
    widget = _zoomed()
    widget.set_course_position(3000.0)

    widget.course_zoom_button.click()

    assert not widget.course_zoomed
    assert _x_range(widget) == pytest.approx((0.0, 5000.0))
    _, (y_min, y_max) = widget._course_plot.getViewBox().viewRange()
    assert y_min <= 100.0 and y_max >= 250.0


def test_zooming_in_mid_ride_starts_the_view_at_the_rider():
    _qapp()
    widget = WorkoutChartWidget()
    widget.load_course(_long_course())
    widget.set_course_position(2200.0)

    widget.course_zoom_button.click()

    assert _x_range(widget) == pytest.approx((2200.0, 3200.0))


def test_reloading_a_course_starts_the_zoomed_view_at_the_start():
    widget = _zoomed()
    widget.set_course_position(3000.0)

    widget.load_course(_long_course())

    assert widget.course_zoomed
    assert _x_range(widget) == pytest.approx((0.0, 1000.0))


def test_ridden_road_is_highlighted_in_the_zoomed_view():
    widget = _zoomed()

    widget.set_course_position(1200.0)
    widget.set_course_position(1500.0)

    distances, _ = widget._course_ridden.getOriginalDataset()
    assert distances[-1] == pytest.approx(1500.0)


def test_zoom_button_sits_top_right_unless_the_road_climbs_into_that_corner():
    _qapp()
    widget = WorkoutChartWidget()
    widget.load_course(_course())  # ends on a descent at the right
    assert widget.course_zoom_button_corner == "right"

    widget.load_course(_long_course())  # climbs to its highest point at the right
    assert widget.course_zoom_button_corner == "left"


# ── Position dot ──────────────────────────────────────────────────────────────

def _dot(widget: WorkoutChartWidget) -> tuple[float, float]:
    x, y = widget._course_dot.getData()
    return float(x[0]), float(y[0])


def test_position_dot_sits_on_the_profile_at_the_rider():
    _qapp()
    widget = WorkoutChartWidget()
    widget.load_course(_course())

    assert _dot(widget) == pytest.approx((0.0, 100.0))

    widget.set_course_position(1500.0)

    assert _dot(widget) == pytest.approx((1500.0, 140.0))


def test_position_dot_follows_the_rider_in_the_zoomed_view():
    widget = _zoomed()

    widget.set_course_position(2500.0)

    assert _dot(widget) == pytest.approx((2500.0, 125.0))


# ── Grade colours ─────────────────────────────────────────────────────────────

def _graded_course() -> Course:
    """1 km each of flat, +4.5 %, +8 %, +12 % and -12 %."""
    profile = ((0.0, 0.0), (1000.0, 0.0), (2000.0, 45.0), (3000.0, 125.0), (4000.0, 245.0), (5000.0, 125.0))
    return Course(
        name="Graded",
        points=tuple(CoursePoint(distance_m=d, elevation_m=e) for d, e in profile),
    )


def _band_segments(widget: WorkoutChartWidget, band: str) -> list[tuple[float, float]]:
    """(start, end) distances of the profile segments coloured as *band*."""
    distances, _ = widget._course_grade_items[band].getOriginalDataset()
    if distances is None:
        return []
    return [(float(a), float(b)) for a, b in zip(distances[::2], distances[1::2])]


@pytest.mark.parametrize(
    "grade, band",
    [
        (-12.0, None), (0.0, None), (2.9, None),
        (3.0, "moderate"), (6.0, "moderate"),
        (6.1, "steep"), (10.0, "steep"),
        (10.1, "very_steep"), (20.0, "very_steep"),
    ],
)
def test_grade_bands(grade, band):
    assert course_grade_band(grade) == band


def test_climbs_are_coloured_by_grade():
    _qapp()
    widget = WorkoutChartWidget()

    widget.load_course(_graded_course())

    assert _band_segments(widget, "moderate") == [(1000.0, 2000.0)]
    assert _band_segments(widget, "steep") == [(2000.0, 3000.0)]
    assert _band_segments(widget, "very_steep") == [(3000.0, 4000.0)]


def test_grade_colours_can_be_turned_off():
    _qapp()
    widget = WorkoutChartWidget()
    widget.load_course(_graded_course())

    widget.set_course_grade_colors(False)

    for band in ("moderate", "steep", "very_steep"):
        assert _band_segments(widget, band) == []

    widget.set_course_grade_colors(True)

    assert _band_segments(widget, "steep") == [(2000.0, 3000.0)]


def test_grade_colours_follow_the_zoomed_view():
    _qapp()
    widget = WorkoutChartWidget()
    widget.load_course(_graded_course())
    widget.course_zoom_button.click()

    widget.set_course_position(2000.0)

    assert _band_segments(widget, "steep") == [(2000.0, 3000.0)]
    assert _band_segments(widget, "moderate") == []

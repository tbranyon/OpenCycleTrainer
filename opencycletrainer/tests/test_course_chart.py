from __future__ import annotations

import os

import numpy as np
import pytest

from opencycletrainer.core.course_model import Course, CoursePoint
from opencycletrainer.ui.workout_chart import WorkoutChartWidget


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


def test_distance_axis_labels_kilometres():
    from opencycletrainer.ui.workout_chart import _DistanceAxisItem

    _qapp()
    axis = _DistanceAxisItem("bottom")

    assert axis.tickStrings([0.0, 2500.0, 10000.0], 1.0, 2500.0) == ["0", "2.5", "10"]

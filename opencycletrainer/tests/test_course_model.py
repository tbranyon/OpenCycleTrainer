from __future__ import annotations

import pytest

from opencycletrainer.core.course_model import GRADE_WINDOW_METERS, Course, CoursePoint


def _course(*profile: tuple[float, float]) -> Course:
    """Build a course from (distance_m, elevation_m) pairs."""
    return Course(
        name="Test Course",
        points=tuple(CoursePoint(distance_m=d, elevation_m=e) for d, e in profile),
    )


def _climb_then_descent() -> Course:
    # 1 km flat, 1 km at +5 %, 1 km at -10 %.
    return _course((0.0, 100.0), (1000.0, 100.0), (2000.0, 150.0), (3000.0, 50.0))


# ── Construction ──────────────────────────────────────────────────────────────

def test_course_requires_at_least_two_points():
    with pytest.raises(ValueError):
        _course((0.0, 100.0))


def test_course_requires_increasing_distances():
    with pytest.raises(ValueError):
        _course((0.0, 100.0), (50.0, 101.0), (50.0, 102.0))


# ── Totals ────────────────────────────────────────────────────────────────────

def test_total_distance_is_the_last_points_distance():
    assert _climb_then_descent().total_distance_m == 3000.0


def test_total_ascent_counts_only_climbing():
    assert _climb_then_descent().total_ascent_m == pytest.approx(50.0)


def test_elevation_range_spans_the_profile():
    course = _climb_then_descent()

    assert course.min_elevation_m == 50.0
    assert course.max_elevation_m == 150.0


# ── Elevation lookup ──────────────────────────────────────────────────────────

def test_elevation_is_interpolated_between_points():
    assert _climb_then_descent().elevation_at(1500.0) == pytest.approx(125.0)


def test_elevation_is_clamped_to_the_course_ends():
    course = _climb_then_descent()

    assert course.elevation_at(-10.0) == 100.0
    assert course.elevation_at(99999.0) == 50.0


# ── Grade lookup ──────────────────────────────────────────────────────────────

def test_grade_matches_the_segment_slope_away_from_transitions():
    course = _climb_then_descent()

    assert course.grade_percent_at(500.0) == pytest.approx(0.0)
    assert course.grade_percent_at(1500.0) == pytest.approx(5.0)
    assert course.grade_percent_at(2500.0) == pytest.approx(-10.0)


def test_grade_is_averaged_across_a_transition():
    course = _climb_then_descent()

    # Centred on the 0 % -> 5 % transition the window is half on each side.
    assert course.grade_percent_at(1000.0) == pytest.approx(2.5)


def test_grade_window_smooths_a_single_noisy_point():
    spike = _course((0.0, 100.0), (100.0, 100.0), (101.0, 101.0), (102.0, 100.0), (200.0, 100.0))

    assert GRADE_WINDOW_METERS > 2.0
    assert abs(spike.grade_percent_at(100.5)) < 100.0 / GRADE_WINDOW_METERS + 1e-6


def test_grade_is_defined_at_the_course_ends():
    course = _climb_then_descent()

    assert course.grade_percent_at(0.0) == pytest.approx(0.0)
    assert course.grade_percent_at(3000.0) == pytest.approx(-10.0)
    assert course.grade_percent_at(-50.0) == pytest.approx(0.0)
    assert course.grade_percent_at(5000.0) == pytest.approx(-10.0)


def test_grade_of_a_course_shorter_than_the_window_uses_the_whole_course():
    short = _course((0.0, 10.0), (10.0, 11.0))

    assert short.grade_percent_at(5.0) == pytest.approx(10.0)


# ── Position lookup ───────────────────────────────────────────────────────────

def test_position_is_interpolated_between_points():
    course = Course(
        name="Line",
        points=(
            CoursePoint(distance_m=0.0, elevation_m=0.0, latitude_deg=45.0, longitude_deg=7.0),
            CoursePoint(distance_m=100.0, elevation_m=0.0, latitude_deg=45.002, longitude_deg=7.004),
        ),
    )

    latitude, longitude = course.position_at(25.0)

    assert latitude == pytest.approx(45.0005)
    assert longitude == pytest.approx(7.001)


def test_position_is_none_without_coordinates():
    assert _climb_then_descent().position_at(100.0) is None

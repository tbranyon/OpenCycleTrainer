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


# ── Sections ──────────────────────────────────────────────────────────────────

def test_section_starts_at_zero_and_spans_the_chosen_stretch():
    section = _climb_then_descent().section(500.0, 2500.0)

    assert section.points[0].distance_m == 0.0
    assert section.total_distance_m == pytest.approx(2000.0)


def test_section_follows_the_original_profile():
    course = _climb_then_descent()

    section = course.section(500.0, 2500.0)

    for offset_m in (0.0, 500.0, 1000.0, 1500.0, 2000.0):
        assert section.elevation_at(offset_m) == pytest.approx(course.elevation_at(500.0 + offset_m))


def test_section_without_a_start_begins_at_the_start_of_the_course():
    section = _climb_then_descent().section(None, 1500.0)

    assert section.total_distance_m == pytest.approx(1500.0)
    assert section.elevation_at(0.0) == pytest.approx(100.0)


def test_section_without_an_end_runs_to_the_end_of_the_course():
    section = _climb_then_descent().section(1500.0, None)

    assert section.total_distance_m == pytest.approx(1500.0)
    assert section.elevation_at(section.total_distance_m) == pytest.approx(50.0)


def test_section_on_existing_points_keeps_them_once():
    section = _climb_then_descent().section(1000.0, 2000.0)

    assert [point.distance_m for point in section.points] == [0.0, 1000.0]


def test_section_interpolates_positions_at_its_ends():
    course = Course(
        name="Located",
        points=(
            CoursePoint(distance_m=0.0, elevation_m=10.0, latitude_deg=45.0, longitude_deg=7.0),
            CoursePoint(distance_m=100.0, elevation_m=20.0, latitude_deg=45.1, longitude_deg=7.2),
        ),
    )

    section = course.section(25.0, 75.0)

    assert section.position_at(0.0) == pytest.approx((45.025, 7.05))
    assert section.position_at(section.total_distance_m) == pytest.approx((45.075, 7.15))


def test_section_end_beyond_the_course_is_clamped_to_the_end():
    assert _climb_then_descent().section(2000.0, 9000.0).total_distance_m == pytest.approx(1000.0)


def test_section_keeps_the_course_name_unless_given_one():
    course = _climb_then_descent()

    assert course.section(0.0, 1000.0).name == "Test Course"
    assert course.section(0.0, 1000.0, name="Opening flat").name == "Opening flat"


@pytest.mark.parametrize("start_m, end_m", [(2000.0, 1000.0), (1500.0, 1500.0), (3000.0, None)])
def test_section_with_no_length_is_rejected(start_m, end_m):
    with pytest.raises(ValueError):
        _climb_then_descent().section(start_m, end_m)


def test_section_with_a_negative_start_is_rejected():
    with pytest.raises(ValueError):
        _climb_then_descent().section(-1.0, 1000.0)


# ── Laps ──────────────────────────────────────────────────────────────────────

def _loop() -> Course:
    """A square loop of four ~111 m sides that ends where it starts, climbing then descending."""
    corners = ((45.0, 7.0), (45.001, 7.0), (45.001, 7.0014142), (45.0, 7.0014142), (45.0, 7.0))
    elevations = (100.0, 105.0, 110.0, 105.0, 100.0)
    side_m = 111.195
    return Course(
        name="Loop",
        points=tuple(
            CoursePoint(
                distance_m=index * side_m,
                elevation_m=elevation,
                latitude_deg=latitude,
                longitude_deg=longitude,
            )
            for index, ((latitude, longitude), elevation) in enumerate(zip(corners, elevations))
        ),
    )


def test_laps_of_a_closed_loop_repeat_its_length():
    loop = _loop()

    assert loop.laps(3).total_distance_m == pytest.approx(3 * loop.total_distance_m)


def test_each_lap_repeats_the_profile():
    loop = _loop()

    laps = loop.laps(3)

    for lap in range(3):
        for offset_m in (0.0, 100.0, 250.0, 400.0):
            assert laps.elevation_at(lap * loop.total_distance_m + offset_m) == pytest.approx(
                loop.elevation_at(offset_m)
            )


def test_laps_add_up_the_climbing():
    loop = _loop()

    assert loop.laps(4).total_ascent_m == pytest.approx(4 * loop.total_ascent_m)


def test_laps_of_a_route_that_does_not_return_ride_back_to_the_start_between_laps():
    out_and_away = Course(
        name="Point to point",
        points=(
            CoursePoint(distance_m=0.0, elevation_m=100.0, latitude_deg=45.0, longitude_deg=7.0),
            CoursePoint(distance_m=111.195, elevation_m=110.0, latitude_deg=45.001, longitude_deg=7.0),
        ),
    )

    laps = out_and_away.laps(2)

    assert laps.total_distance_m == pytest.approx(3 * 111.195, rel=1e-3)
    assert laps.elevation_at(laps.total_distance_m) == pytest.approx(110.0)


def test_one_lap_is_the_course_itself():
    loop = _loop()

    assert loop.laps(1).points == loop.points


def test_laps_keep_the_course_name_unless_given_one():
    loop = _loop()

    assert loop.laps(2).name == "Loop"
    assert loop.laps(2, name="Loop x2").name == "Loop x2"


@pytest.mark.parametrize("count", [0, -1])
def test_lap_count_must_be_at_least_one(count):
    with pytest.raises(ValueError):
        _loop().laps(count)


# ── Lap numbers ───────────────────────────────────────────────────────────────

def test_a_course_is_a_single_lap():
    course = _climb_then_descent()

    assert course.lap_count == 1
    assert course.lap_number_at(0.0) == 1
    assert course.lap_number_at(course.total_distance_m) == 1


def test_laps_number_each_repeat_of_a_loop():
    loop = _loop()
    lap_m = loop.total_distance_m

    laps = loop.laps(3)

    assert laps.lap_count == 3
    assert laps.lap_number_at(0.0) == 1
    assert laps.lap_number_at(lap_m - 1.0) == 1
    assert laps.lap_number_at(lap_m + 1.0) == 2
    assert laps.lap_number_at(2 * lap_m + 1.0) == 3
    assert laps.lap_number_at(laps.total_distance_m) == 3


def test_the_ride_back_to_the_start_belongs_to_the_lap_before_it():
    out_and_away = Course(
        name="Point to point",
        points=(
            CoursePoint(distance_m=0.0, elevation_m=100.0, latitude_deg=45.0, longitude_deg=7.0),
            CoursePoint(distance_m=111.195, elevation_m=110.0, latitude_deg=45.001, longitude_deg=7.0),
        ),
    )

    laps = out_and_away.laps(2)

    assert laps.lap_number_at(150.0) == 1
    assert laps.lap_number_at(2 * 111.195 + 1.0) == 2


def test_a_section_of_laps_is_a_single_lap():
    assert _loop().laps(3).section(100.0, 900.0).lap_count == 1


def test_lap_starts_must_begin_at_the_start_and_lie_on_the_course():
    points = _climb_then_descent().points
    with pytest.raises(ValueError):
        Course(name="Bad", points=points, lap_starts_m=(500.0,))
    with pytest.raises(ValueError):
        Course(name="Bad", points=points, lap_starts_m=(0.0, 2000.0, 1000.0))
    with pytest.raises(ValueError):
        Course(name="Bad", points=points, lap_starts_m=(0.0, 3000.0))

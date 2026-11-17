from __future__ import annotations

import pytest

from opencycletrainer.core.course_model import Course, CoursePoint
from opencycletrainer.core.course_ride import CourseRide

MASS_KG = 84.0
STEP_SECONDS = 0.25


def _course(*profile: tuple[float, float]) -> Course:
    return Course(
        name="Ride Test",
        points=tuple(CoursePoint(distance_m=d, elevation_m=e) for d, e in profile),
    )


def _flat(length_m: float = 1000.0) -> Course:
    return _course((0.0, 50.0), (length_m, 50.0))


def _ride(ride: CourseRide, seconds: float, power_watts: float) -> None:
    for _ in range(int(seconds / STEP_SECONDS)):
        ride.advance(STEP_SECONDS, power_watts)


def test_new_ride_starts_stationary_at_the_course_start():
    ride = CourseRide(_flat(), total_mass_kg=MASS_KG)

    assert ride.distance_m == 0.0
    assert ride.speed_mps == 0.0
    assert ride.remaining_m == 1000.0
    assert not ride.finished


def test_pedaling_moves_the_rider_along_the_course():
    ride = CourseRide(_flat(), total_mass_kg=MASS_KG)

    _ride(ride, 20.0, 200.0)

    assert ride.speed_mps > 5.0
    assert 50.0 < ride.distance_m < 200.0
    assert ride.remaining_m == pytest.approx(1000.0 - ride.distance_m)


def test_distance_is_the_integral_of_speed():
    ride = CourseRide(_flat(100_000.0), total_mass_kg=MASS_KG)
    _ride(ride, 600.0, 200.0)
    cruising_speed = ride.speed_mps
    distance_before = ride.distance_m

    _ride(ride, 10.0, 200.0)

    assert ride.distance_m - distance_before == pytest.approx(cruising_speed * 10.0, rel=0.01)


def test_grade_and_elevation_follow_the_riders_position():
    course = _course((0.0, 100.0), (1000.0, 100.0), (2000.0, 150.0))
    ride = CourseRide(course, total_mass_kg=MASS_KG)
    assert ride.grade_percent == pytest.approx(0.0)

    while ride.distance_m < 1500.0:
        ride.advance(STEP_SECONDS, 250.0)

    assert ride.grade_percent == pytest.approx(5.0)
    assert ride.elevation_m == pytest.approx(course.elevation_at(ride.distance_m))


def test_climb_slows_the_rider_at_constant_power():
    course = _course((0.0, 0.0), (5000.0, 0.0), (10000.0, 400.0))
    ride = CourseRide(course, total_mass_kg=MASS_KG)
    while ride.distance_m < 4000.0:
        ride.advance(STEP_SECONDS, 200.0)
    flat_speed = ride.speed_mps

    while ride.distance_m < 9000.0:
        ride.advance(STEP_SECONDS, 200.0)

    assert ride.speed_mps < flat_speed / 2


def test_ride_finishes_at_the_end_of_the_course_and_stays_there():
    ride = CourseRide(_flat(100.0), total_mass_kg=MASS_KG)

    _ride(ride, 120.0, 250.0)

    assert ride.finished
    assert ride.distance_m == 100.0
    assert ride.remaining_m == 0.0

    ride.advance(STEP_SECONDS, 250.0)

    assert ride.distance_m == 100.0


def test_halt_stops_the_bike_without_losing_progress():
    ride = CourseRide(_flat(), total_mass_kg=MASS_KG)
    _ride(ride, 20.0, 200.0)
    distance = ride.distance_m

    ride.halt()

    assert ride.speed_mps == 0.0
    assert ride.distance_m == distance


def test_reset_returns_to_the_course_start():
    ride = CourseRide(_flat(), total_mass_kg=MASS_KG)
    _ride(ride, 20.0, 200.0)

    ride.reset()

    assert ride.distance_m == 0.0
    assert ride.speed_mps == 0.0
    assert not ride.finished


def test_a_stalled_clock_cannot_teleport_the_rider():
    ride = CourseRide(_flat(100_000.0), total_mass_kg=MASS_KG)
    _ride(ride, 60.0, 200.0)
    distance = ride.distance_m
    speed = ride.speed_mps

    ride.advance(3600.0, 200.0)

    assert ride.distance_m - distance < speed * 30.0


def test_negative_or_missing_power_is_treated_as_coasting():
    ride = CourseRide(_flat(), total_mass_kg=MASS_KG)
    _ride(ride, 20.0, 200.0)
    speed = ride.speed_mps

    ride.advance(1.0, -50.0)

    assert 0.0 < ride.speed_mps < speed


def test_position_follows_course_coordinates():
    course = Course(
        name="Line",
        points=(
            CoursePoint(distance_m=0.0, elevation_m=0.0, latitude_deg=45.0, longitude_deg=7.0),
            CoursePoint(distance_m=1000.0, elevation_m=0.0, latitude_deg=45.009, longitude_deg=7.0),
        ),
    )
    ride = CourseRide(course, total_mass_kg=MASS_KG)

    _ride(ride, 30.0, 200.0)

    latitude, longitude = ride.position
    assert 45.0 < latitude < 45.009
    assert longitude == pytest.approx(7.0)


# ── Rolling resistance ────────────────────────────────────────────────────────

_GRAVEL_ROLLING_RESISTANCE = 0.012


def test_higher_rolling_resistance_slows_the_ride():
    smooth = CourseRide(_flat(100_000.0), total_mass_kg=MASS_KG)
    gravel = CourseRide(
        _flat(100_000.0), total_mass_kg=MASS_KG, rolling_resistance=_GRAVEL_ROLLING_RESISTANCE
    )

    _ride(smooth, 300.0, 200.0)
    _ride(gravel, 300.0, 200.0)

    assert gravel.speed_mps < smooth.speed_mps - 0.5
    assert gravel.distance_m < smooth.distance_m


def test_rolling_resistance_can_change_mid_ride():
    ride = CourseRide(_flat(100_000.0), total_mass_kg=MASS_KG)
    _ride(ride, 300.0, 200.0)
    smooth_speed = ride.speed_mps

    ride.set_rolling_resistance(_GRAVEL_ROLLING_RESISTANCE)
    _ride(ride, 300.0, 200.0)

    assert ride.speed_mps < smooth_speed - 0.5

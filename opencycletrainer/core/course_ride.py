from __future__ import annotations

from .bike_physics import advance_speed
from .course_model import Course

MAX_ADVANCE_SECONDS = 5.0
"""Longest time one advance() may cover, so a stalled clock cannot jump the rider ahead."""


class CourseRide:
    """Tracks a rider's virtual progress along a course, driven by their power output."""

    def __init__(self, course: Course, *, total_mass_kg: float) -> None:
        self._course = course
        self._total_mass_kg = float(total_mass_kg)
        self._distance_m = 0.0
        self._speed_mps = 0.0

    @property
    def course(self) -> Course:
        return self._course

    @property
    def distance_m(self) -> float:
        return self._distance_m

    @property
    def remaining_m(self) -> float:
        return self._course.total_distance_m - self._distance_m

    @property
    def speed_mps(self) -> float:
        return self._speed_mps

    @property
    def finished(self) -> bool:
        return self._distance_m >= self._course.total_distance_m

    @property
    def grade_percent(self) -> float:
        """Grade of the road under the rider."""
        return self._course.grade_percent_at(self._distance_m)

    @property
    def elevation_m(self) -> float:
        return self._course.elevation_at(self._distance_m)

    @property
    def position(self) -> tuple[float, float] | None:
        """The rider's (latitude, longitude), or None if the course has no coordinates."""
        return self._course.position_at(self._distance_m)

    def set_total_mass_kg(self, total_mass_kg: float) -> None:
        """Change the rider + bike mass used from the next advance on."""
        self._total_mass_kg = float(total_mass_kg)

    def advance(self, dt_seconds: float, power_watts: float | None) -> None:
        """Ride for *dt_seconds* at *power_watts*; no-op once the course is finished."""
        if self.finished:
            return
        dt = min(max(0.0, float(dt_seconds)), MAX_ADVANCE_SECONDS)
        previous_speed = self._speed_mps
        self._speed_mps = advance_speed(
            previous_speed,
            power_watts or 0.0,
            self.grade_percent,
            self._total_mass_kg,
            dt,
        )
        travelled = (previous_speed + self._speed_mps) / 2.0 * dt
        self._distance_m = min(self._distance_m + travelled, self._course.total_distance_m)

    def halt(self) -> None:
        """Bring the bike to a stop where it is, e.g. when the ride is paused."""
        self._speed_mps = 0.0

    def reset(self) -> None:
        """Return to the start of the course, stationary."""
        self._distance_m = 0.0
        self._speed_mps = 0.0

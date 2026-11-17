from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, field

GRADE_WINDOW_METERS = 50.0
"""Length of road the reported grade is averaged over, which smooths elevation noise."""

_PERCENT = 100.0
_MIN_COURSE_POINTS = 2


@dataclass(frozen=True)
class CoursePoint:
    """One point of a course profile: distance from the start and elevation there."""

    distance_m: float
    elevation_m: float
    latitude_deg: float | None = None
    longitude_deg: float | None = None


@dataclass(frozen=True)
class Course:
    """A distance-based route with an elevation profile, ridden from start to end."""

    name: str
    points: tuple[CoursePoint, ...]
    _distances: tuple[float, ...] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if len(self.points) < _MIN_COURSE_POINTS:
            raise ValueError("A course needs at least two points.")
        distances = tuple(point.distance_m for point in self.points)
        if any(later <= earlier for earlier, later in zip(distances, distances[1:])):
            raise ValueError("Course point distances must be strictly increasing.")
        object.__setattr__(self, "_distances", distances)

    @property
    def total_distance_m(self) -> float:
        return self._distances[-1]

    @property
    def total_ascent_m(self) -> float:
        """Sum of every elevation gain along the course."""
        elevations = [point.elevation_m for point in self.points]
        return sum(max(0.0, later - earlier) for earlier, later in zip(elevations, elevations[1:]))

    @property
    def min_elevation_m(self) -> float:
        return min(point.elevation_m for point in self.points)

    @property
    def max_elevation_m(self) -> float:
        return max(point.elevation_m for point in self.points)

    def elevation_at(self, distance_m: float) -> float:
        """Return the elevation at *distance_m*, clamped to the ends of the course."""
        earlier, later, ratio = self._bracket(distance_m)
        return earlier.elevation_m + (later.elevation_m - earlier.elevation_m) * ratio

    def grade_percent_at(self, distance_m: float, window_m: float = GRADE_WINDOW_METERS) -> float:
        """Return the grade averaged over *window_m* of road centred on *distance_m*.

        Near either end the window slides inward so it always covers real road.
        """
        start_m = self._distances[0]
        end_m = self._distances[-1]
        span = min(float(window_m), end_m - start_m)
        window_start = min(max(float(distance_m) - span / 2.0, start_m), end_m - span)
        window_end = window_start + span
        rise = self.elevation_at(window_end) - self.elevation_at(window_start)
        return rise / span * _PERCENT

    def position_at(self, distance_m: float) -> tuple[float, float] | None:
        """Return (latitude, longitude) at *distance_m*, or None if the course has no coordinates."""
        earlier, later, ratio = self._bracket(distance_m)
        coordinates = (
            earlier.latitude_deg, earlier.longitude_deg, later.latitude_deg, later.longitude_deg,
        )
        if any(value is None for value in coordinates):
            return None
        latitude = earlier.latitude_deg + (later.latitude_deg - earlier.latitude_deg) * ratio
        longitude = earlier.longitude_deg + (later.longitude_deg - earlier.longitude_deg) * ratio
        return latitude, longitude

    def _bracket(self, distance_m: float) -> tuple[CoursePoint, CoursePoint, float]:
        """Return the points either side of *distance_m* and how far between them it lies (0-1)."""
        clamped = min(max(float(distance_m), self._distances[0]), self._distances[-1])
        upper = min(bisect_right(self._distances, clamped), len(self.points) - 1)
        earlier = self.points[upper - 1]
        later = self.points[upper]
        ratio = (clamped - earlier.distance_m) / (later.distance_m - earlier.distance_m)
        return earlier, later, ratio

from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field
import math

GRADE_WINDOW_METERS = 50.0
"""Length of road the reported grade is averaged over, which smooths elevation noise."""

_PERCENT = 100.0
_MIN_COURSE_POINTS = 2
_EARTH_RADIUS_METERS = 6_371_000.0
_LAP_CLOSURE_METERS = 0.5
"""A lap ending closer than this to the start is treated as a closed loop, with no link between laps."""


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

    def section(
        self, start_m: float | None, end_m: float | None, name: str | None = None
    ) -> Course:
        """Return the stretch from *start_m* to *end_m*, re-measured from zero.

        A missing start or end means the start or end of the course; an end past the
        course is clamped to it. The new ends are interpolated from the original profile.
        """
        course_end_m = self.total_distance_m
        start = 0.0 if start_m is None else float(start_m)
        end = course_end_m if end_m is None else min(float(end_m), course_end_m)
        if start < 0.0:
            raise ValueError("A section cannot start before the course does.")
        if end <= start:
            raise ValueError("A section must end after it starts.")

        first_inside = bisect_right(self._distances, start)
        past_inside = bisect_left(self._distances, end)
        inside = self.points[first_inside:past_inside]
        points = (
            [self._point_at(start, offset_m=start)]
            + [_shifted(point, -start) for point in inside]
            + [self._point_at(end, offset_m=start)]
        )
        return Course(name=self.name if name is None else name, points=tuple(points))

    def laps(self, count: int, name: str | None = None) -> Course:
        """Return the course ridden *count* times in a row.

        A route that does not end where it starts gets a straight link from its end
        back to its start between laps.
        """
        if count < 1:
            raise ValueError("A course must be ridden at least once.")
        link_m = self._closing_gap_m()
        is_loop = link_m < _LAP_CLOSURE_METERS
        lap_length_m = self.total_distance_m + (0.0 if is_loop else link_m)
        repeated_points = self.points[1:] if is_loop else self.points
        points = list(self.points)
        for lap in range(1, count):
            points.extend(_shifted(point, lap * lap_length_m) for point in repeated_points)
        return Course(name=self.name if name is None else name, points=tuple(points))

    def _closing_gap_m(self) -> float:
        """Straight-line distance from the course's end back to its start, 0 without coordinates."""
        first = self.points[0]
        last = self.points[-1]
        coordinates = (first.latitude_deg, first.longitude_deg, last.latitude_deg, last.longitude_deg)
        if any(value is None for value in coordinates):
            return 0.0
        return haversine_meters(*coordinates)

    def _point_at(self, distance_m: float, offset_m: float) -> CoursePoint:
        """Return an interpolated point at *distance_m*, measured from *offset_m*."""
        latitude, longitude = self.position_at(distance_m) or (None, None)
        return CoursePoint(
            distance_m=distance_m - offset_m,
            elevation_m=self.elevation_at(distance_m),
            latitude_deg=latitude,
            longitude_deg=longitude,
        )

    def _bracket(self, distance_m: float) -> tuple[CoursePoint, CoursePoint, float]:
        """Return the points either side of *distance_m* and how far between them it lies (0-1)."""
        clamped = min(max(float(distance_m), self._distances[0]), self._distances[-1])
        upper = min(bisect_right(self._distances, clamped), len(self.points) - 1)
        earlier = self.points[upper - 1]
        later = self.points[upper]
        ratio = (clamped - earlier.distance_m) / (later.distance_m - earlier.distance_m)
        return earlier, later, ratio


def _shifted(point: CoursePoint, by_m: float) -> CoursePoint:
    """Return *point* moved *by_m* metres along the course."""
    return CoursePoint(
        distance_m=point.distance_m + by_m,
        elevation_m=point.elevation_m,
        latitude_deg=point.latitude_deg,
        longitude_deg=point.longitude_deg,
    )


def haversine_meters(
    latitude_a: float, longitude_a: float, latitude_b: float, longitude_b: float
) -> float:
    """Return the great-circle distance in metres between two coordinates in degrees."""
    phi_a = math.radians(latitude_a)
    phi_b = math.radians(latitude_b)
    delta_phi = phi_b - phi_a
    delta_lambda = math.radians(longitude_b - longitude_a)
    half_chord = (
        math.sin(delta_phi / 2.0) ** 2
        + math.cos(phi_a) * math.cos(phi_b) * math.sin(delta_lambda / 2.0) ** 2
    )
    return 2.0 * _EARTH_RADIUS_METERS * math.asin(min(1.0, math.sqrt(half_chord)))

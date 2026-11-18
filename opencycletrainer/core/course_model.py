from __future__ import annotations

from bisect import bisect_left, bisect_right
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
    """A distance-based route with an elevation profile, ridden from start to end.

    *lap_starts_m* marks where each lap begins; a plain course is a single lap. Where
    one lap hands over to the next, the finish of one and the start of the next may
    share a distance: the rider jumps straight back to the start, elevation and all.
    """

    name: str
    points: tuple[CoursePoint, ...]
    lap_starts_m: tuple[float, ...] = (0.0,)
    _distances: tuple[float, ...] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if len(self.points) < _MIN_COURSE_POINTS:
            raise ValueError("A course needs at least two points.")
        distances = tuple(point.distance_m for point in self.points)
        lap_changes = set(self.lap_starts_m[1:])
        for before, earlier, later in zip((None,) + distances, distances, distances[1:]):
            shared_at_lap_change = later == earlier and later in lap_changes and before != earlier
            if later < earlier or (later == earlier and not shared_at_lap_change):
                raise ValueError("Course point distances must be strictly increasing.")
        laps = self.lap_starts_m
        if not laps or laps[0] > distances[0]:
            raise ValueError("The first lap must begin at the start of the course.")
        if any(later <= earlier for earlier, later in zip(laps, laps[1:])):
            raise ValueError("Lap starts must be strictly increasing.")
        if laps[-1] >= distances[-1]:
            raise ValueError("Every lap must begin before the end of the course.")
        object.__setattr__(self, "_distances", distances)

    @property
    def total_distance_m(self) -> float:
        return self._distances[-1]

    @property
    def lap_count(self) -> int:
        return len(self.lap_starts_m)

    def lap_number_at(self, distance_m: float) -> int:
        """Return the 1-based lap that *distance_m* falls in, clamped to the first and last lap."""
        return max(1, bisect_right(self.lap_starts_m, float(distance_m)))

    @property
    def total_ascent_m(self) -> float:
        """Sum of every elevation gain along the course; the jump back to the start between laps is not climbing."""
        return sum(
            max(0.0, later.elevation_m - earlier.elevation_m)
            for earlier, later in zip(self.points, self.points[1:])
            if later.distance_m > earlier.distance_m
        )

    @property
    def min_elevation_m(self) -> float:
        return min(point.elevation_m for point in self.points)

    @property
    def max_elevation_m(self) -> float:
        return max(point.elevation_m for point in self.points)

    def elevation_at(self, distance_m: float, *, from_before: bool = False) -> float:
        """Return the elevation at *distance_m*, clamped to the ends of the course.

        At a lap change this is the next lap's start, or with *from_before* the finish
        of the lap before it.
        """
        earlier, later, ratio = self._bracket(distance_m, from_before)
        return earlier.elevation_m + (later.elevation_m - earlier.elevation_m) * ratio

    def grade_percent_at(self, distance_m: float, window_m: float = GRADE_WINDOW_METERS) -> float:
        """Return the grade averaged over *window_m* of road centred on *distance_m*.

        The window stays within the lap *distance_m* is in, sliding inward near either
        end of it, so it always covers real road and never the jump between laps.
        """
        lap_index = self.lap_number_at(distance_m) - 1
        start_m = max(self.lap_starts_m[lap_index], self._distances[0])
        is_last_lap = lap_index + 1 == self.lap_count
        end_m = self._distances[-1] if is_last_lap else self.lap_starts_m[lap_index + 1]
        span = min(float(window_m), end_m - start_m)
        window_start = min(max(float(distance_m) - span / 2.0, start_m), end_m - span)
        window_end = window_start + span
        rise = self.elevation_at(window_end, from_before=True) - self.elevation_at(window_start)
        return rise / span * _PERCENT

    def position_at(
        self, distance_m: float, *, from_before: bool = False
    ) -> tuple[float, float] | None:
        """Return (latitude, longitude) at *distance_m*, or None if the course has no coordinates.

        At a lap change this is the next lap's start, or with *from_before* the finish
        of the lap before it.
        """
        earlier, later, ratio = self._bracket(distance_m, from_before)
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
        course is clamped to it. The new ends are interpolated from the original profile,
        and lap changes inside the stretch are kept.
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
            + [self._point_at(end, offset_m=start, from_before=True)]
        )
        lap_changes = tuple(lap_start - start for lap_start in self.lap_starts_m if start < lap_start < end)
        return Course(
            name=self.name if name is None else name,
            points=tuple(points),
            lap_starts_m=(0.0,) + lap_changes,
        )

    def laps(self, count: int, name: str | None = None) -> Course:
        """Return the course ridden *count* times in a row.

        Each lap starts again from the start as soon as the one before it finishes, even
        when the route does not finish where it starts.
        """
        if count < 1:
            raise ValueError("A course must be ridden at least once.")
        first_m = self._distances[0]
        lap_length_m = self.total_distance_m - first_m
        points = list(self.points)
        lap_starts = list(self.lap_starts_m)
        for lap in range(1, count):
            offset_m = lap * lap_length_m
            points.extend(_shifted(point, offset_m) for point in self.points)
            lap_starts.append(first_m + offset_m)
            lap_starts.extend(lap_start + offset_m for lap_start in self.lap_starts_m[1:])
        return Course(
            name=self.name if name is None else name,
            points=tuple(points),
            lap_starts_m=tuple(lap_starts),
        )

    def _point_at(self, distance_m: float, offset_m: float, from_before: bool = False) -> CoursePoint:
        """Return an interpolated point at *distance_m*, measured from *offset_m*."""
        latitude, longitude = self.position_at(distance_m, from_before=from_before) or (None, None)
        return CoursePoint(
            distance_m=distance_m - offset_m,
            elevation_m=self.elevation_at(distance_m, from_before=from_before),
            latitude_deg=latitude,
            longitude_deg=longitude,
        )

    def _bracket(
        self, distance_m: float, from_before: bool = False
    ) -> tuple[CoursePoint, CoursePoint, float]:
        """Return the points either side of *distance_m* and how far between them it lies (0-1).

        Where two points share a distance at a lap change, the pair after it is used, or
        with *from_before* the pair before it.
        """
        clamped = min(max(float(distance_m), self._distances[0]), self._distances[-1])
        if from_before:
            upper = max(1, min(bisect_left(self._distances, clamped), len(self.points) - 1))
        else:
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


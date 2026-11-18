"""Shared building blocks for reading course files (GPX, TCX, FIT) into a Course.

Every format is measured the same way: distance is accumulated from the points'
coordinates, so a route reads the same whichever file it came in. Points of interest
are placed on that distance scale, by the time or distance the file gives for them when
it has one, else by the nearest point of the route to where they are.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np

from .course_model import CoursePoi, CoursePoint

EARTH_RADIUS_METERS = 6_371_000.0
MIN_POINT_SPACING_METERS = 0.5
"""Points closer than this to the previous one are dropped as stationary GPS repeats."""
MAX_POI_OFFSET_METERS = 100.0
"""A point of interest placed by position must be this close to the route to count as on it."""


class CourseFileError(ValueError):
    """Raised when a course file cannot be turned into a rideable course."""


@dataclass(frozen=True)
class TrackSample:
    """One located point read from a course file, with the time or distance the file stamps it with."""

    latitude_deg: float
    longitude_deg: float
    elevation_m: float
    anchor: float | None = None


@dataclass(frozen=True)
class PoiCandidate:
    """A point of interest as a file describes it, before it is placed along the route.

    *anchor* is in the same terms as the track samples' anchors (a time or the file's own
    distance), so it can be placed exactly even on a route that passes the same spot twice.
    """

    name: str = ""
    notes: str = ""
    kind: str = ""
    latitude_deg: float | None = None
    longitude_deg: float | None = None
    anchor: float | None = None


def haversine_meters(latitude_a: float, longitude_a: float, latitude_b: float, longitude_b: float) -> float:
    """Return the great-circle distance in metres between two coordinates in degrees."""
    phi_a = math.radians(latitude_a)
    phi_b = math.radians(latitude_b)
    delta_phi = phi_b - phi_a
    delta_lambda = math.radians(longitude_b - longitude_a)
    half_chord = (
        math.sin(delta_phi / 2.0) ** 2
        + math.cos(phi_a) * math.cos(phi_b) * math.sin(delta_lambda / 2.0) ** 2
    )
    return 2.0 * EARTH_RADIUS_METERS * math.asin(min(1.0, math.sqrt(half_chord)))


def build_course_points(samples: list[TrackSample]) -> tuple[list[CoursePoint], list[float | None]]:
    """Accumulate distance along *samples*, dropping ones that do not advance.

    Returns the course points and, for each, the anchor of the sample it came from.
    """
    first = samples[0]
    points = [CoursePoint(0.0, first.elevation_m, first.latitude_deg, first.longitude_deg)]
    anchors: list[float | None] = [first.anchor]
    for sample in samples[1:]:
        previous = points[-1]
        step = haversine_meters(
            previous.latitude_deg, previous.longitude_deg, sample.latitude_deg, sample.longitude_deg,
        )
        if step < MIN_POINT_SPACING_METERS:
            continue
        points.append(
            CoursePoint(previous.distance_m + step, sample.elevation_m, sample.latitude_deg, sample.longitude_deg)
        )
        anchors.append(sample.anchor)
    return points, anchors


def place_pois(
    points: list[CoursePoint], anchors: list[float | None], candidates: list[PoiCandidate],
) -> tuple[CoursePoi, ...]:
    """Place each candidate along the route, leaving out any that cannot be placed on it."""
    by_anchor = _anchor_lookup(points, anchors)
    placed = []
    for candidate in candidates:
        distance_m = by_anchor(candidate.anchor) if candidate.anchor is not None else None
        if distance_m is None and candidate.latitude_deg is not None and candidate.longitude_deg is not None:
            distance_m = _distance_along_nearest(points, candidate.latitude_deg, candidate.longitude_deg)
        if distance_m is not None:
            placed.append(CoursePoi(distance_m, candidate.name, candidate.notes, candidate.kind))
    return tuple(placed)


def _anchor_lookup(points: list[CoursePoint], anchors: list[float | None]):
    """Return a function from an anchor to a distance along the route, or to None outside the track."""
    known = [(anchor, point.distance_m) for anchor, point in zip(anchors, points) if anchor is not None]
    keys = np.array([anchor for anchor, _ in known], dtype=float)
    if len(keys) < 2 or np.any(np.diff(keys) < 0):
        return lambda _anchor: None
    distances = np.array([distance for _, distance in known], dtype=float)

    def lookup(anchor: float) -> float | None:
        if not keys[0] <= anchor <= keys[-1]:
            return None
        return float(np.interp(anchor, keys, distances))

    return lookup


def _distance_along_nearest(points: list[CoursePoint], latitude: float, longitude: float) -> float | None:
    """Return how far along the route its nearest point to (latitude, longitude) is, if close enough."""
    metres_per_degree = math.pi * EARTH_RADIUS_METERS / 180.0
    x_scale = metres_per_degree * math.cos(math.radians(latitude))
    xs = np.array([(point.longitude_deg - longitude) * x_scale for point in points])
    ys = np.array([(point.latitude_deg - latitude) * metres_per_degree for point in points])
    seg_x, seg_y = np.diff(xs), np.diff(ys)
    lengths_sq = seg_x**2 + seg_y**2
    with np.errstate(invalid="ignore", divide="ignore"):
        along = np.where(lengths_sq > 0, -(xs[:-1] * seg_x + ys[:-1] * seg_y) / lengths_sq, 0.0)
    along = np.clip(along, 0.0, 1.0)
    offsets = np.hypot(xs[:-1] + along * seg_x, ys[:-1] + along * seg_y)
    nearest = int(np.argmin(offsets))
    if offsets[nearest] > MAX_POI_OFFSET_METERS:
        return None
    start, end = points[nearest].distance_m, points[nearest + 1].distance_m
    return start + float(along[nearest]) * (end - start)

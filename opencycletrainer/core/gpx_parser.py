from __future__ import annotations

import math
from pathlib import Path
import xml.etree.ElementTree as ET

from .course_model import Course, CoursePoint

_EARTH_RADIUS_METERS = 6_371_000.0
_MIN_POINT_SPACING_METERS = 0.5
"""Points closer than this to the previous one are dropped as stationary GPS repeats."""

_DEFAULT_COURSE_NAME = "Course"
_ROOT_TAG = "gpx"
_TRACK_POINT_TAG = "trkpt"
_ROUTE_POINT_TAG = "rtept"
_NAME_PARENT_TAGS = ("metadata", "trk", "rte")


class GPXParseError(ValueError):
    """Raised when GPX content cannot be turned into a rideable course."""


def parse_gpx_file(path: Path) -> Course:
    """Parse a GPX file at *path* into a Course, named after the file if it has no name."""
    text = path.read_text(encoding="utf-8-sig")
    return parse_gpx_text(text, fallback_name=path.stem)


def parse_gpx_text(text: str, fallback_name: str = _DEFAULT_COURSE_NAME) -> Course:
    """Parse GPX XML text into a Course.

    Track points are used when present, route points otherwise. Points without an
    elevation are skipped, since grade cannot be simulated across them.
    """
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise GPXParseError(f"Invalid XML: {exc}") from exc

    if _local_tag(root) != _ROOT_TAG:
        raise GPXParseError("Root element must be <gpx>.")

    elements = _point_elements(root)
    if not elements:
        raise GPXParseError("GPX file contains no track or route points.")

    located = [_parse_point(element) for element in elements]
    with_elevation = [point for point in located if point[2] is not None]
    if not with_elevation:
        raise GPXParseError("GPX file has no elevation data.")

    points = _build_course_points(with_elevation)
    if len(points) < 2:
        raise GPXParseError("GPX file does not describe a route with any length.")

    return Course(name=_course_name(root) or fallback_name, points=tuple(points))


def _local_tag(element: ET.Element) -> str:
    """Return an element's tag without its XML namespace, so any GPX version matches."""
    return element.tag.rsplit("}", 1)[-1]


def _point_elements(root: ET.Element) -> list[ET.Element]:
    track_points = [element for element in root.iter() if _local_tag(element) == _TRACK_POINT_TAG]
    if track_points:
        return track_points
    return [element for element in root.iter() if _local_tag(element) == _ROUTE_POINT_TAG]


def _parse_point(element: ET.Element) -> tuple[float, float, float | None]:
    """Return (latitude, longitude, elevation) for a point element; elevation may be None."""
    try:
        latitude = float(element.attrib["lat"])
        longitude = float(element.attrib["lon"])
    except (KeyError, ValueError) as exc:
        raise GPXParseError("GPX point is missing a valid lat/lon.") from exc
    if not (math.isfinite(latitude) and math.isfinite(longitude)):
        raise GPXParseError("GPX point is missing a valid lat/lon.")

    elevation: float | None = None
    for child in element:
        if _local_tag(child) != "ele":
            continue
        try:
            elevation = float((child.text or "").strip())
        except ValueError:
            elevation = None
        if elevation is not None and not math.isfinite(elevation):
            elevation = None
        break
    return latitude, longitude, elevation


def _build_course_points(located: list[tuple[float, float, float]]) -> list[CoursePoint]:
    """Accumulate distance along *located* points, dropping ones that do not advance."""
    first_latitude, first_longitude, first_elevation = located[0]
    points = [
        CoursePoint(
            distance_m=0.0,
            elevation_m=first_elevation,
            latitude_deg=first_latitude,
            longitude_deg=first_longitude,
        )
    ]
    for latitude, longitude, elevation in located[1:]:
        previous = points[-1]
        step = _haversine_meters(
            previous.latitude_deg, previous.longitude_deg, latitude, longitude
        )
        if step < _MIN_POINT_SPACING_METERS:
            continue
        points.append(
            CoursePoint(
                distance_m=previous.distance_m + step,
                elevation_m=elevation,
                latitude_deg=latitude,
                longitude_deg=longitude,
            )
        )
    return points


def _haversine_meters(
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


def _course_name(root: ET.Element) -> str:
    """Return the first non-empty name from the metadata, track or route, else an empty string."""
    for parent_tag in _NAME_PARENT_TAGS:
        for parent in root:
            if _local_tag(parent) != parent_tag:
                continue
            for child in parent:
                if _local_tag(child) == "name" and (child.text or "").strip():
                    return child.text.strip()
    return ""

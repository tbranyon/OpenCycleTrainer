from __future__ import annotations

import math
from pathlib import Path
import xml.etree.ElementTree as ET

from .course_files import CourseFileError, PoiCandidate, TrackSample, build_course_points, place_pois
from .course_model import Course

_DEFAULT_COURSE_NAME = "Course"
_ROOT_TAG = "gpx"
_TRACK_POINT_TAG = "trkpt"
_ROUTE_POINT_TAG = "rtept"
_WAYPOINT_TAG = "wpt"
_NAME_PARENT_TAGS = ("metadata", "trk", "rte")
_WAYPOINT_NOTE_TAGS = ("desc", "cmt")


class GPXParseError(CourseFileError):
    """Raised when GPX content cannot be turned into a rideable course."""


def parse_gpx_file(path: Path) -> Course:
    """Parse a GPX file at *path* into a Course, named after the file if it has no name."""
    text = path.read_text(encoding="utf-8-sig")
    return parse_gpx_text(text, fallback_name=path.stem)


def parse_gpx_text(text: str, fallback_name: str = _DEFAULT_COURSE_NAME) -> Course:
    """Parse GPX XML text into a Course.

    Track points are used when present, route points otherwise. Points without an
    elevation are skipped, since grade cannot be simulated across them. Waypoints near
    the route become its points of interest.
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

    points, anchors = build_course_points([TrackSample(*point) for point in with_elevation])
    if len(points) < 2:
        raise GPXParseError("GPX file does not describe a route with any length.")

    return Course(
        name=_course_name(root) or fallback_name,
        points=tuple(points),
        pois=place_pois(points, anchors, _waypoints(root)),
    )


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


def _waypoints(root: ET.Element) -> list[PoiCandidate]:
    """Return the file's waypoints with their name, description and type."""
    candidates = []
    for element in root:
        if _local_tag(element) != _WAYPOINT_TAG:
            continue
        try:
            latitude, longitude, _ = _parse_point(element)
        except GPXParseError:
            continue
        texts = {_local_tag(child): (child.text or "").strip() for child in element}
        notes = next((texts[tag] for tag in _WAYPOINT_NOTE_TAGS if texts.get(tag)), "")
        candidates.append(PoiCandidate(
            name=texts.get("name", ""), notes=notes, kind=texts.get("type", ""),
            latitude_deg=latitude, longitude_deg=longitude,
        ))
    return candidates


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

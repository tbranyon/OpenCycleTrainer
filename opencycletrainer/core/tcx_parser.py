"""Reading Garmin TCX courses (and activities) into a Course.

A TCX course is a track of trackpoints plus course points. Course points that are
turn cues are left out; the rest become the course's points of interest, with the name,
notes and point type the file gives them.
"""

from __future__ import annotations

from datetime import datetime
import math
from pathlib import Path
import xml.etree.ElementTree as ET

from .course_files import CourseFileError, PoiCandidate, TrackSample, build_course_points, place_pois
from .course_model import Course

_ROOT_TAG = "TrainingCenterDatabase"
_TRACKPOINT_TAG = "Trackpoint"
_COURSE_POINT_TAG = "CoursePoint"
_COURSE_TAG = "Course"

_TURN_CUE_TYPES = frozenset({"Left", "Right", "Straight"})
_KIND_BY_POINT_TYPE = {
    "Generic": "",
    "First Aid": "First aid",
    "4th Category": "Category 4 climb",
    "3rd Category": "Category 3 climb",
    "2nd Category": "Category 2 climb",
    "1st Category": "Category 1 climb",
    "Hors Category": "Hors catégorie climb",
}


class TCXParseError(CourseFileError):
    """Raised when TCX content cannot be turned into a rideable course."""


def parse_tcx_file(path: Path) -> Course:
    """Parse a TCX file at *path* into a Course, named after the file if it has no course name."""
    return parse_tcx_text(path.read_text(encoding="utf-8-sig"), fallback_name=path.stem)


def parse_tcx_text(text: str, fallback_name: str = "Course") -> Course:
    """Parse TCX XML text into a Course; trackpoints without a position or altitude are skipped."""
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise TCXParseError(f"Invalid XML: {exc}") from exc
    if _local_tag(root) != _ROOT_TAG:
        raise TCXParseError("Root element must be <TrainingCenterDatabase>.")

    trackpoints = [element for element in root.iter() if _local_tag(element) == _TRACKPOINT_TAG]
    if not trackpoints:
        raise TCXParseError("TCX file contains no trackpoints.")
    samples = [sample for sample in map(_track_sample, trackpoints) if sample is not None]
    if not samples:
        raise TCXParseError("TCX file has no trackpoints with a position and altitude.")

    points, anchors = build_course_points(samples)
    if len(points) < 2:
        raise TCXParseError("TCX file does not describe a route with any length.")
    course_points = (_course_point(element) for element in root.iter() if _local_tag(element) == _COURSE_POINT_TAG)
    candidates = [candidate for candidate in course_points if candidate is not None]
    return Course(
        name=_course_name(root) or fallback_name,
        points=tuple(points),
        pois=place_pois(points, anchors, candidates),
    )


def _local_tag(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _child(element: ET.Element, tag: str) -> ET.Element | None:
    return next((child for child in element if _local_tag(child) == tag), None)


def _text(element: ET.Element, tag: str) -> str:
    child = _child(element, tag)
    return (child.text or "").strip() if child is not None else ""


def _number(element: ET.Element, tag: str) -> float | None:
    try:
        value = float(_text(element, tag))
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def _position(element: ET.Element) -> tuple[float, float] | None:
    position = _child(element, "Position")
    if position is None:
        return None
    latitude = _number(position, "LatitudeDegrees")
    longitude = _number(position, "LongitudeDegrees")
    if latitude is None or longitude is None:
        return None
    return latitude, longitude


def _timestamp(element: ET.Element) -> float | None:
    """Return the element's <Time> as seconds since the epoch, or None."""
    text = _text(element, "Time")
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _track_sample(element: ET.Element) -> TrackSample | None:
    position = _position(element)
    altitude = _number(element, "AltitudeMeters")
    if position is None or altitude is None:
        return None
    return TrackSample(position[0], position[1], altitude, anchor=_timestamp(element))


def _course_point(element: ET.Element) -> PoiCandidate | None:
    """Return a point of interest for a course point, or None for a turn cue."""
    point_type = _text(element, "PointType")
    if point_type in _TURN_CUE_TYPES:
        return None
    latitude, longitude = _position(element) or (None, None)
    return PoiCandidate(
        name=_text(element, "Name"),
        notes=_text(element, "Notes"),
        kind=_KIND_BY_POINT_TYPE.get(point_type, point_type),
        latitude_deg=latitude,
        longitude_deg=longitude,
        anchor=_timestamp(element),
    )


def _course_name(root: ET.Element) -> str:
    """Return the first course's name, or an empty string (activities have none)."""
    for element in root.iter():
        if _local_tag(element) == _COURSE_TAG:
            name = _text(element, "Name")
            if name:
                return name
    return ""

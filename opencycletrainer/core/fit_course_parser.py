"""Reading FIT course files (and activities) into a Course.

The route comes from the file's located record messages; its course points, except
turn cues, become points of interest with the name and type the file gives them. The
FIT format carries no notes for a course point.
"""

from __future__ import annotations

import logging
import math
from pathlib import Path

from .course_files import CourseFileError, PoiCandidate, TrackSample, build_course_points, place_pois
from .course_model import Course

_logger = logging.getLogger(__name__)

_RECORD_MESSAGE = "RecordMessage"
_COURSE_MESSAGE = "CourseMessage"
_COURSE_POINT_MESSAGE = "CoursePointMessage"

_TURN_CUE_TYPES = frozenset({
    "LEFT", "RIGHT", "STRAIGHT", "LEFT_FORK", "RIGHT_FORK", "MIDDLE_FORK",
    "SLIGHT_LEFT", "SHARP_LEFT", "SLIGHT_RIGHT", "SHARP_RIGHT", "U_TURN",
})
_KIND_BY_POINT_TYPE = {
    "GENERIC": "",
    "FOURTH_CATEGORY": "Category 4 climb",
    "THIRD_CATEGORY": "Category 3 climb",
    "SECOND_CATEGORY": "Category 2 climb",
    "FIRST_CATEGORY": "Category 1 climb",
    "HORS_CATEGORY": "Hors catégorie climb",
}


class FITCourseParseError(CourseFileError):
    """Raised when a FIT file cannot be turned into a rideable course."""


def parse_fit_course_file(path: Path) -> Course:
    """Parse the FIT file at *path* into a Course, named after the file if it has no course name."""
    from fit_tool.fit_file import FitFile  # noqa: PLC0415 (decoding pulls in the whole FIT profile)

    try:
        messages = [record.message for record in FitFile.from_file(str(path)).records]
    except OSError:
        raise
    except Exception as exc:  # noqa: BLE001 (fit-tool raises many kinds of error on a bad file)
        _logger.info("Could not decode FIT file %s: %r", path, exc)
        raise FITCourseParseError("Not a readable FIT file.") from exc

    samples = [sample for sample in map(_track_sample, _of_type(messages, _RECORD_MESSAGE)) if sample]
    if not samples:
        raise FITCourseParseError("FIT file has no located points with an altitude.")
    points, anchors = build_course_points(samples)
    if len(points) < 2:
        raise FITCourseParseError("FIT file does not describe a route with any length.")
    candidates = [
        candidate
        for candidate in map(_course_point, _of_type(messages, _COURSE_POINT_MESSAGE))
        if candidate is not None
    ]
    return Course(
        name=_course_name(messages) or path.stem,
        points=tuple(points),
        pois=place_pois(points, anchors, candidates),
    )


def _of_type(messages: list, type_name: str) -> list:
    return [message for message in messages if type(message).__name__ == type_name]


def _finite(value) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _track_sample(record) -> TrackSample | None:
    latitude = _finite(getattr(record, "position_lat", None))
    longitude = _finite(getattr(record, "position_long", None))
    altitude = _finite(getattr(record, "enhanced_altitude", None))
    if altitude is None:
        altitude = _finite(getattr(record, "altitude", None))
    if latitude is None or longitude is None or altitude is None:
        return None
    return TrackSample(latitude, longitude, altitude, anchor=_finite(getattr(record, "distance", None)))


def _point_type_name(value) -> str:
    from fit_tool.profile.profile_type import CoursePoint  # noqa: PLC0415

    try:
        return CoursePoint(int(value)).name
    except (TypeError, ValueError):
        return "GENERIC"


def _course_point(message) -> PoiCandidate | None:
    """Return a point of interest for a course point, or None for a turn cue."""
    type_name = _point_type_name(getattr(message, "type", None))
    if type_name in _TURN_CUE_TYPES:
        return None
    kind = _KIND_BY_POINT_TYPE.get(type_name, type_name.replace("_", " ").capitalize())
    return PoiCandidate(
        name=(getattr(message, "course_point_name", None) or "").strip(),
        kind=kind,
        latitude_deg=_finite(getattr(message, "position_lat", None)),
        longitude_deg=_finite(getattr(message, "position_long", None)),
        anchor=_finite(getattr(message, "distance", None)),
    )


def _course_name(messages: list) -> str:
    for message in _of_type(messages, _COURSE_MESSAGE):
        name = (getattr(message, "course_name", None) or "").strip()
        if name:
            return name
    return ""

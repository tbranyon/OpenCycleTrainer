from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from opencycletrainer.core.tcx_parser import TCXParseError, parse_tcx_file, parse_tcx_text

# One thousandth of a degree of latitude on the parsers' spherical earth.
MILLIDEGREE_LATITUDE_METERS = 111.195
_START = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
_SECONDS_PER_POINT = 30


def _time(index: int) -> str:
    return (_START + timedelta(seconds=index * _SECONDS_PER_POINT)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _position(index: int) -> str:
    return (
        f"<Position><LatitudeDegrees>{45.0 + index * 0.001}</LatitudeDegrees>"
        f"<LongitudeDegrees>7.0</LongitudeDegrees></Position>"
    )


def _trackpoint(index: int, elevation: float | None) -> str:
    altitude = f"<AltitudeMeters>{elevation}</AltitudeMeters>" if elevation is not None else ""
    return (
        f"<Trackpoint><Time>{_time(index)}</Time>{_position(index)}{altitude}"
        f"<DistanceMeters>{index * 111.0}</DistanceMeters></Trackpoint>"
    )


def _course_point(index: int, point_type: str, *, name: str = "", notes: str = "", timed: bool = True) -> str:
    name_xml = f"<Name>{name}</Name>" if name else ""
    notes_xml = f"<Notes>{notes}</Notes>" if notes else ""
    time_xml = f"<Time>{_time(index)}</Time>" if timed else ""
    return f"<CoursePoint>{name_xml}{time_xml}{_position(index)}<PointType>{point_type}</PointType>{notes_xml}</CoursePoint>"


def _course_tcx(elevations, course_points: str = "", name: str = "Hill Loop") -> str:
    points = "".join(_trackpoint(index, elevation) for index, elevation in enumerate(elevations))
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<TrainingCenterDatabase xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2">'
        f"<Courses><Course><Name>{name}</Name><Track>{points}</Track>{course_points}</Course></Courses>"
        "</TrainingCenterDatabase>"
    )


_HILL = [100.0, 100.0, 105.0, 110.0, 105.0]


def test_a_tcx_course_is_read_with_its_name_and_profile():
    course = parse_tcx_text(_course_tcx(_HILL))

    assert course.name == "Hill Loop"
    assert [point.elevation_m for point in course.points] == _HILL
    assert course.total_distance_m == pytest.approx(4 * MILLIDEGREE_LATITUDE_METERS, rel=1e-3)
    assert course.points[2].latitude_deg == pytest.approx(45.002)


def test_a_tcx_activity_can_be_ridden_as_a_course(tmp_path):
    points = "".join(_trackpoint(index, elevation) for index, elevation in enumerate(_HILL))
    path = tmp_path / "Morning Ride.tcx"
    path.write_text(
        '<?xml version="1.0"?><TrainingCenterDatabase xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2">'
        f'<Activities><Activity Sport="Biking"><Id>{_time(0)}</Id><Lap StartTime="{_time(0)}">'
        f"<Track>{points}</Track></Lap></Activity></Activities></TrainingCenterDatabase>",
        encoding="utf-8",
    )

    course = parse_tcx_file(path)

    assert course.name == "Morning Ride"
    assert len(course.points) == len(_HILL)


def test_tcx_course_points_become_points_of_interest_where_they_were_passed():
    course = parse_tcx_text(_course_tcx(_HILL, _course_point(3, "Summit", name="Top", notes="Views")))

    (poi,) = course.pois
    assert (poi.name, poi.notes, poi.kind) == ("Top", "Views", "Summit")
    assert poi.distance_m == pytest.approx(3 * MILLIDEGREE_LATITUDE_METERS, rel=1e-3)


def test_a_tcx_course_point_without_a_time_is_placed_by_its_position():
    course = parse_tcx_text(_course_tcx(_HILL, _course_point(2, "Water", name="Fountain", timed=False)))

    (poi,) = course.pois
    assert poi.kind == "Water"
    assert poi.distance_m == pytest.approx(2 * MILLIDEGREE_LATITUDE_METERS, rel=1e-3)


def test_tcx_turn_cues_are_not_points_of_interest():
    cues = "".join(
        _course_point(index, point_type, name=f"Turn {index}")
        for index, point_type in enumerate(("Left", "Right", "Straight"), start=1)
    )
    course = parse_tcx_text(_course_tcx(_HILL, cues + _course_point(4, "Generic", name="Bench")))

    assert [(poi.name, poi.kind) for poi in course.pois] == [("Bench", "")]


@pytest.mark.parametrize(
    "text",
    [
        "<TrainingCenterDatabase",
        '<?xml version="1.0"?><gpx></gpx>',
        _course_tcx([]),
        _course_tcx([None, None, None]),
    ],
    ids=["invalid-xml", "wrong-root", "no-trackpoints", "no-altitude"],
)
def test_tcx_that_is_not_a_rideable_course_is_rejected(text):
    with pytest.raises(TCXParseError):
        parse_tcx_text(text)


def test_tcx_course_file_is_read_from_disk(tmp_path):
    path = tmp_path / "hill.tcx"
    path.write_text(_course_tcx(_HILL), encoding="utf-8")

    assert parse_tcx_file(Path(path)).name == "Hill Loop"

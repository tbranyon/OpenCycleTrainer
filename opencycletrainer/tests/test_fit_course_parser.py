from __future__ import annotations

from pathlib import Path

import pytest

from opencycletrainer.core.fit_course_parser import FITCourseParseError, parse_fit_course_file

# One thousandth of a degree of latitude on the parsers' spherical earth.
MILLIDEGREE_LATITUDE_METERS = 111.195
_START_MS = 1_767_261_600_000  # 2026-01-01 10:00 UTC
_HILL = [100.0, 100.0, 105.0, 110.0, 105.0]


def write_fit_course(
    path: Path,
    elevations=_HILL,
    course_points=(),
    *,
    name: str | None = "Hill Loop",
    positioned: bool = True,
) -> Path:
    """Write a FIT course heading north, one record every ~111 m; *course_points* are (index, type, name)."""
    from fit_tool.fit_file_builder import FitFileBuilder
    from fit_tool.profile.messages.course_message import CourseMessage
    from fit_tool.profile.messages.course_point_message import CoursePointMessage
    from fit_tool.profile.messages.file_id_message import FileIdMessage
    from fit_tool.profile.messages.record_message import RecordMessage
    from fit_tool.profile.profile_type import CoursePoint, FileType, Manufacturer, Sport

    builder = FitFileBuilder(auto_define=True, min_string_size=50)
    file_id = FileIdMessage()
    file_id.type = FileType.COURSE
    file_id.manufacturer = Manufacturer.DEVELOPMENT.value
    file_id.product = 0
    file_id.serial_number = 1
    file_id.time_created = _START_MS
    builder.add(file_id)
    if name is not None:
        course = CourseMessage()
        course.course_name = name
        course.sport = Sport.CYCLING
        builder.add(course)
    for index, elevation in enumerate(elevations):
        record = RecordMessage()
        record.timestamp = _START_MS + index * 30_000
        if positioned:
            record.position_lat = 45.0 + index * 0.001
            record.position_long = 7.0
        record.distance = index * 111.0
        record.altitude = elevation
        builder.add(record)
    for index, point_type, point_name in course_points:
        point = CoursePointMessage()
        point.timestamp = _START_MS + index * 30_000
        point.position_lat = 45.0 + index * 0.001
        point.position_long = 7.0
        point.distance = index * 111.0
        point.type = getattr(CoursePoint, point_type)
        if point_name:
            point.course_point_name = point_name
        builder.add(point)
    builder.build().to_file(str(path))
    return path


def test_a_fit_course_is_read_with_its_name_and_profile(tmp_path):
    course = parse_fit_course_file(write_fit_course(tmp_path / "hill.fit"))

    assert course.name == "Hill Loop"
    assert [point.elevation_m for point in course.points] == pytest.approx(_HILL)
    assert course.total_distance_m == pytest.approx(4 * MILLIDEGREE_LATITUDE_METERS, rel=1e-3)
    assert course.points[2].latitude_deg == pytest.approx(45.002, abs=1e-6)


def test_a_fit_course_without_a_name_is_named_after_the_file(tmp_path):
    course = parse_fit_course_file(write_fit_course(tmp_path / "Sunday Loop.fit", name=None))

    assert course.name == "Sunday Loop"


@pytest.mark.parametrize(
    ("point_type", "name", "expected"),
    [
        ("SUMMIT", "Col du Test", ("Col du Test", "Summit")),
        ("FOURTH_CATEGORY", "", ("", "Category 4 climb")),
        ("AID_STATION", "Feed", ("Feed", "Aid station")),
        ("GENERIC", "Bench", ("Bench", "")),
    ],
)
def test_fit_course_points_become_points_of_interest_at_their_distance(tmp_path, point_type, name, expected):
    path = write_fit_course(tmp_path / "hill.fit", course_points=[(3, point_type, name)])

    (poi,) = parse_fit_course_file(path).pois

    assert (poi.name, poi.kind) == expected
    assert poi.notes == ""
    assert poi.distance_m == pytest.approx(3 * MILLIDEGREE_LATITUDE_METERS, rel=1e-3)


def test_fit_turn_cues_are_not_points_of_interest(tmp_path):
    cues = [(1, "LEFT", "Left"), (2, "SLIGHT_RIGHT", "Bear right"), (3, "U_TURN", ""), (4, "WATER", "Tap")]

    course = parse_fit_course_file(write_fit_course(tmp_path / "hill.fit", course_points=cues))

    assert [poi.name for poi in course.pois] == ["Tap"]


def test_a_file_that_is_not_fit_is_rejected(tmp_path):
    path = tmp_path / "broken.fit"
    path.write_bytes(b"this is not a FIT file at all")

    with pytest.raises(FITCourseParseError):
        parse_fit_course_file(path)


def test_a_fit_file_without_positions_is_rejected(tmp_path):
    with pytest.raises(FITCourseParseError):
        parse_fit_course_file(write_fit_course(tmp_path / "indoor.fit", positioned=False))

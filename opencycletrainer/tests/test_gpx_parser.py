from __future__ import annotations

from pathlib import Path
import textwrap

import pytest

from opencycletrainer.core.gpx_parser import GPXParseError, parse_gpx_file, parse_gpx_text

DATA_DIR = Path(__file__).parent / "data"

# One thousandth of a degree of latitude on the parser's spherical earth.
MILLIDEGREE_LATITUDE_METERS = 111.195


# ── Helpers ───────────────────────────────────────────────────────────────────

def _trkpt(lat: float, lon: float, ele: float | None) -> str:
    ele_xml = f"<ele>{ele}</ele>" if ele is not None else ""
    return f'<trkpt lat="{lat}" lon="{lon}">{ele_xml}</trkpt>'


def _wrap(points_xml: str, *, name_xml: str = "<name>Loop</name>") -> str:
    """Wrap track point XML in a minimal GPX 1.1 document."""
    return textwrap.dedent(f"""\
        <?xml version="1.0" encoding="UTF-8"?>
        <gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">
          <trk>
            {name_xml}
            <trkseg>
              {points_xml}
            </trkseg>
          </trk>
        </gpx>
    """)


def _northward_track(elevations: list[float | None]) -> str:
    return "".join(
        _trkpt(45.0 + index * 0.001, 7.0, elevation)
        for index, elevation in enumerate(elevations)
    )


# ── Geometry ──────────────────────────────────────────────────────────────────

def test_parse_gpx_file_accumulates_distance_across_track_segments():
    course = parse_gpx_file(DATA_DIR / "hill.gpx")

    assert len(course.points) == 5
    assert course.points[0].distance_m == 0.0
    assert course.total_distance_m == pytest.approx(4 * MILLIDEGREE_LATITUDE_METERS, rel=1e-3)
    assert [point.elevation_m for point in course.points] == [100.0, 100.0, 105.0, 110.0, 105.0]


def test_parsed_points_keep_their_coordinates():
    course = parse_gpx_file(DATA_DIR / "hill.gpx")

    assert course.points[2].latitude_deg == pytest.approx(45.002)
    assert course.points[2].longitude_deg == pytest.approx(7.0)


def test_distance_follows_longitude_at_the_tracks_latitude():
    points = _trkpt(60.0, 10.0, 5.0) + _trkpt(60.0, 10.001, 5.0)

    course = parse_gpx_text(_wrap(points))

    # A degree of longitude at 60°N spans half the distance it does at the equator.
    assert course.total_distance_m == pytest.approx(MILLIDEGREE_LATITUDE_METERS / 2, rel=1e-3)


def test_repeated_points_do_not_create_zero_length_segments():
    points = (
        _trkpt(45.0, 7.0, 100.0)
        + _trkpt(45.0, 7.0, 100.0)
        + _trkpt(45.001, 7.0, 101.0)
    )

    course = parse_gpx_text(_wrap(points))

    distances = [point.distance_m for point in course.points]
    assert distances == sorted(set(distances))
    assert len(course.points) == 2


# ── Names ─────────────────────────────────────────────────────────────────────

def test_metadata_name_is_preferred_over_track_name():
    course = parse_gpx_file(DATA_DIR / "hill.gpx")

    assert course.name == "Test Hill"


def test_track_name_is_used_when_metadata_has_none():
    course = parse_gpx_text(_wrap(_northward_track([1.0, 2.0]), name_xml="<name>Alpe</name>"))

    assert course.name == "Alpe"


def test_fallback_name_is_used_when_file_has_no_name():
    course = parse_gpx_text(
        _wrap(_northward_track([1.0, 2.0]), name_xml=""),
        fallback_name="my_route",
    )

    assert course.name == "my_route"


def test_parse_gpx_file_falls_back_to_the_file_stem(tmp_path):
    path = tmp_path / "sunday_loop.gpx"
    path.write_text(_wrap(_northward_track([1.0, 2.0]), name_xml=""), encoding="utf-8")

    assert parse_gpx_file(path).name == "sunday_loop"


# ── Variants ──────────────────────────────────────────────────────────────────

def test_route_points_are_used_when_there_is_no_track():
    gpx = textwrap.dedent("""\
        <gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">
          <rte>
            <name>Planned</name>
            <rtept lat="45.000" lon="7.0"><ele>10</ele></rtept>
            <rtept lat="45.001" lon="7.0"><ele>20</ele></rtept>
          </rte>
        </gpx>
    """)

    course = parse_gpx_text(gpx)

    assert course.name == "Planned"
    assert [point.elevation_m for point in course.points] == [10.0, 20.0]


def test_gpx_1_0_namespace_is_accepted():
    gpx = textwrap.dedent("""\
        <gpx version="1.0" xmlns="http://www.topografix.com/GPX/1/0">
          <trk><trkseg>
            <trkpt lat="45.000" lon="7.0"><ele>10</ele></trkpt>
            <trkpt lat="45.001" lon="7.0"><ele>20</ele></trkpt>
          </trkseg></trk>
        </gpx>
    """)

    assert len(parse_gpx_text(gpx).points) == 2


def test_points_without_elevation_are_skipped():
    course = parse_gpx_text(_wrap(_northward_track([100.0, None, 104.0])))

    assert [point.elevation_m for point in course.points] == [100.0, 104.0]
    assert course.total_distance_m == pytest.approx(2 * MILLIDEGREE_LATITUDE_METERS, rel=1e-3)


# ── Errors ────────────────────────────────────────────────────────────────────

def test_malformed_xml_is_rejected():
    with pytest.raises(GPXParseError):
        parse_gpx_text("<gpx><trk>")


def test_non_gpx_root_is_rejected():
    with pytest.raises(GPXParseError):
        parse_gpx_text("<workout_file><name>x</name></workout_file>")


def test_file_without_elevation_is_rejected():
    with pytest.raises(GPXParseError, match="elevation"):
        parse_gpx_text(_wrap(_northward_track([None, None, None])))


def test_file_with_a_single_point_is_rejected():
    with pytest.raises(GPXParseError):
        parse_gpx_text(_wrap(_northward_track([100.0])))


def test_invalid_coordinates_are_rejected():
    points = '<trkpt lat="north" lon="7.0"><ele>1</ele></trkpt>' + _trkpt(45.0, 7.0, 2.0)

    with pytest.raises(GPXParseError):
        parse_gpx_text(_wrap(points))


def test_track_that_never_moves_is_rejected():
    points = _trkpt(45.0, 7.0, 100.0) * 3

    with pytest.raises(GPXParseError):
        parse_gpx_text(_wrap(points))


# ── Waypoints ─────────────────────────────────────────────────────────────────

def _with_waypoints(waypoints_xml: str) -> str:
    return _wrap(_northward_track([100.0, 101.0, 102.0, 103.0, 104.0])).replace(
        "<trk>", waypoints_xml + "<trk>", 1
    )


def test_waypoints_on_the_route_become_points_of_interest_where_the_route_passes_them():
    course = parse_gpx_text(_with_waypoints(
        '<wpt lat="45.0025" lon="7.0003"><name>Fountain</name><desc>Cold water</desc><type>Water</type></wpt>'
    ))

    (poi,) = course.pois
    assert (poi.name, poi.notes, poi.kind) == ("Fountain", "Cold water", "Water")
    assert poi.distance_m == pytest.approx(2.5 * MILLIDEGREE_LATITUDE_METERS, rel=1e-3)


def test_waypoints_far_from_the_route_are_left_out():
    course = parse_gpx_text(_with_waypoints('<wpt lat="45.002" lon="7.02"><name>Castle</name></wpt>'))

    assert course.pois == ()


def test_a_waypoint_without_a_name_is_still_a_point_of_interest():
    course = parse_gpx_text(_with_waypoints('<wpt lat="45.001" lon="7.0"></wpt>'))

    assert [(poi.name, poi.notes) for poi in course.pois] == [("", "")]

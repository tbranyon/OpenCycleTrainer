from __future__ import annotations

import pytest

from opencycletrainer.storage.settings import DISPLAY_UNITS_IMPERIAL, DISPLAY_UNITS_METRIC
from opencycletrainer.ui.ride_format import (
    distance_unit_label,
    elevation_unit_label,
    format_distance,
    format_grade_percent,
    format_speed,
    kilograms_per_weight_unit,
    meters_per_distance_unit,
    meters_per_elevation_unit,
    weight_unit_label,
)

_METERS_PER_MILE = 1609.344
_METERS_PER_FOOT = 0.3048


def test_distance_is_shown_in_kilometres_by_default():
    assert format_distance(12340.0) == "12.34 km"
    assert format_distance(12340.0, DISPLAY_UNITS_METRIC) == "12.34 km"


def test_distance_is_shown_in_miles_for_imperial_units():
    assert format_distance(_METERS_PER_MILE, DISPLAY_UNITS_IMPERIAL) == "1.00 mi"
    assert format_distance(10000.0, DISPLAY_UNITS_IMPERIAL) == "6.21 mi"


def test_negative_distance_is_shown_as_zero():
    assert format_distance(-5.0) == "0.00 km"
    assert format_distance(-5.0, DISPLAY_UNITS_IMPERIAL) == "0.00 mi"


def test_speed_is_shown_in_kmh_by_default():
    assert format_speed(10.0) == "36.0 km/h"


def test_speed_is_shown_in_mph_for_imperial_units():
    assert format_speed(10.0, DISPLAY_UNITS_IMPERIAL) == "22.4 mph"


def test_unknown_units_fall_back_to_metric():
    assert format_distance(1000.0, "furlongs") == "1.00 km"
    assert format_speed(10.0, "furlongs") == "36.0 km/h"


def test_grade_is_shown_the_same_in_both_unit_systems():
    assert format_grade_percent(4.52) == "+4.5 %"
    assert format_grade_percent(-0.01) == "0.0 %"


def test_unit_labels_and_sizes_for_chart_axes():
    assert distance_unit_label(DISPLAY_UNITS_METRIC) == "km"
    assert distance_unit_label(DISPLAY_UNITS_IMPERIAL) == "mi"
    assert elevation_unit_label(DISPLAY_UNITS_METRIC) == "m"
    assert elevation_unit_label(DISPLAY_UNITS_IMPERIAL) == "ft"
    assert meters_per_distance_unit(DISPLAY_UNITS_METRIC) == 1000.0
    assert meters_per_distance_unit(DISPLAY_UNITS_IMPERIAL) == pytest.approx(_METERS_PER_MILE)
    assert meters_per_elevation_unit(DISPLAY_UNITS_METRIC) == 1.0
    assert meters_per_elevation_unit(DISPLAY_UNITS_IMPERIAL) == pytest.approx(_METERS_PER_FOOT)


def test_weight_unit_label_and_size():
    assert weight_unit_label(DISPLAY_UNITS_METRIC) == "kg"
    assert weight_unit_label(DISPLAY_UNITS_IMPERIAL) == "lb"
    assert kilograms_per_weight_unit(DISPLAY_UNITS_METRIC) == 1.0
    assert kilograms_per_weight_unit(DISPLAY_UNITS_IMPERIAL) == pytest.approx(0.45359237)


# ── Point of interest tooltips ────────────────────────────────────────────────

@pytest.mark.parametrize(
    ("poi_kwargs", "rider_m", "units", "expected"),
    [
        (
            dict(name="Col du Test", kind="Summit", notes="Views both ways"),
            9250.0, DISPLAY_UNITS_METRIC,
            "Col du Test\nSummit\nViews both ways\nAt 12.40 km · 3.15 km ahead",
        ),
        (dict(kind="Water"), 0.0, DISPLAY_UNITS_METRIC, "Water\nAt 12.40 km · 12.40 km ahead"),
        (dict(name="Summit", kind="Summit"), 13000.0, DISPLAY_UNITS_METRIC, "Summit\nAt 12.40 km · passed"),
        (dict(), 2340.0, DISPLAY_UNITS_METRIC, "At 12.40 km · 10.06 km ahead"),
        (dict(), 0.0, DISPLAY_UNITS_IMPERIAL, "At 7.71 mi · 7.71 mi ahead"),
    ],
    ids=["details", "kind-only", "passed", "no-details", "imperial"],
)
def test_poi_tooltip_shows_its_details_then_where_it_is(poi_kwargs, rider_m, units, expected):
    from opencycletrainer.core.course_model import CoursePoi
    from opencycletrainer.ui.ride_format import format_poi_tooltip

    poi = CoursePoi(distance_m=12_400.0, **poi_kwargs)

    assert format_poi_tooltip(poi, rider_m, units) == expected

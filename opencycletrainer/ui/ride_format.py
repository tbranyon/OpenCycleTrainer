from __future__ import annotations

from opencycletrainer.storage.settings import DISPLAY_UNITS_IMPERIAL, DISPLAY_UNITS_METRIC

_METERS_PER_KILOMETER = 1000.0
_METERS_PER_MILE = 1609.344
_METERS_PER_FOOT = 0.3048
_KILOGRAMS_PER_POUND = 0.45359237
_SECONDS_PER_HOUR = 3600.0
_GRADE_DISPLAY_STEP_PERCENT = 0.1


def _is_imperial(units: str) -> bool:
    """True for imperial display units; anything else is shown as metric."""
    return units == DISPLAY_UNITS_IMPERIAL


def distance_unit_label(units: str = DISPLAY_UNITS_METRIC) -> str:
    """Return the unit ride distances are shown in: ``km`` or ``mi``."""
    return "mi" if _is_imperial(units) else "km"


def elevation_unit_label(units: str = DISPLAY_UNITS_METRIC) -> str:
    """Return the unit elevations are shown in: ``m`` or ``ft``."""
    return "ft" if _is_imperial(units) else "m"


def meters_per_distance_unit(units: str = DISPLAY_UNITS_METRIC) -> float:
    """Return how many metres one displayed distance unit (km or mi) spans."""
    return _METERS_PER_MILE if _is_imperial(units) else _METERS_PER_KILOMETER


def meters_per_elevation_unit(units: str = DISPLAY_UNITS_METRIC) -> float:
    """Return how many metres one displayed elevation unit (m or ft) spans."""
    return _METERS_PER_FOOT if _is_imperial(units) else 1.0


def weight_unit_label(units: str = DISPLAY_UNITS_METRIC) -> str:
    """Return the unit weights are shown in: ``kg`` or ``lb``."""
    return "lb" if _is_imperial(units) else "kg"


def kilograms_per_weight_unit(units: str = DISPLAY_UNITS_METRIC) -> float:
    """Return how many kilograms one displayed weight unit (kg or lb) weighs."""
    return _KILOGRAMS_PER_POUND if _is_imperial(units) else 1.0


def format_distance(distance_m: float, units: str = DISPLAY_UNITS_METRIC) -> str:
    """Format a distance in metres for display, e.g. ``12.34 km`` or ``7.67 mi``."""
    value = max(0.0, distance_m) / meters_per_distance_unit(units)
    return f"{value:.2f} {distance_unit_label(units)}"


def format_elevation(elevation_m: float, units: str = DISPLAY_UNITS_METRIC) -> str:
    """Format an elevation or climb in metres for display, e.g. ``328 ft`` or ``100 m``."""
    value = elevation_m / meters_per_elevation_unit(units)
    return f"{value:.0f} {elevation_unit_label(units)}"


def format_speed(speed_mps: float, units: str = DISPLAY_UNITS_METRIC) -> str:
    """Format a speed in m/s for display, e.g. ``31.5 km/h`` or ``19.6 mph``."""
    value = max(0.0, speed_mps) * _SECONDS_PER_HOUR / meters_per_distance_unit(units)
    return f"{value:.1f} {'mph' if _is_imperial(units) else 'km/h'}"


def format_grade_percent(grade_percent: float) -> str:
    """Format a grade with its sign, e.g. ``+4.5 %``; a level road reads ``0.0 %``."""
    rounded = round(grade_percent / _GRADE_DISPLAY_STEP_PERCENT) * _GRADE_DISPLAY_STEP_PERCENT
    if rounded == 0:
        return "0.0 %"
    return f"{rounded:+.1f} %"

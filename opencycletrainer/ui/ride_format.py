from __future__ import annotations

_METERS_PER_KILOMETER = 1000.0
_KMH_PER_MPS = 3.6
_GRADE_DISPLAY_STEP_PERCENT = 0.1


def format_distance_km(distance_m: float) -> str:
    """Format a distance in metres as kilometres, e.g. ``12.34 km``."""
    return f"{max(0.0, distance_m) / _METERS_PER_KILOMETER:.2f} km"


def format_speed_kmh(speed_mps: float) -> str:
    """Format a speed in m/s as km/h, e.g. ``31.5 km/h``."""
    return f"{max(0.0, speed_mps) * _KMH_PER_MPS:.1f} km/h"


def format_grade_percent(grade_percent: float) -> str:
    """Format a grade with its sign, e.g. ``+4.5 %``; a level road reads ``0.0 %``."""
    rounded = round(grade_percent / _GRADE_DISPLAY_STEP_PERCENT) * _GRADE_DISPLAY_STEP_PERCENT
    if rounded == 0:
        return "0.0 %"
    return f"{rounded:+.1f} %"

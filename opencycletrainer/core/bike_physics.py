from __future__ import annotations

import math

from opencycletrainer.storage.settings import (
    ROAD_SURFACE_AGED_ASPHALT,
    ROAD_SURFACE_CHIPSEAL,
    ROAD_SURFACE_GRAVEL,
    ROAD_SURFACE_HARDPACK_GRAVEL,
    ROAD_SURFACE_LOOSE_GRAVEL,
    ROAD_SURFACE_SMOOTH_ROAD,
)

GRAVITY_MPS2 = 9.80665

ROLLING_RESISTANCE_COEFFICIENT = 0.004
"""Crr of a fast road tyre on smooth asphalt (unitless); the default surface."""

ROLLING_RESISTANCE_BY_SURFACE: dict[str, float] = {
    ROAD_SURFACE_SMOOTH_ROAD: ROLLING_RESISTANCE_COEFFICIENT,
    ROAD_SURFACE_AGED_ASPHALT: 0.005,
    ROAD_SURFACE_CHIPSEAL: 0.007,
    ROAD_SURFACE_HARDPACK_GRAVEL: 0.008,
    ROAD_SURFACE_GRAVEL: 0.012,
    ROAD_SURFACE_LOOSE_GRAVEL: 0.020,
}
"""Approximate Crr per road surface, for a tyre suited to that surface."""

WIND_RESISTANCE_KG_PER_M = 0.25
"""Cw = half air density x CdA, for a rider on the hoods at sea level (kg/m)."""

_PERCENT = 100.0
_MIN_DRIVE_SPEED_MPS = 1.0
"""Speed floor used when turning power into force, so a standing start is not infinite force."""

_MAX_STEP_SECONDS = 0.1
"""Longest single integration step; longer time spans are split into steps of this size."""


def rolling_resistance_for_surface(surface: str) -> float:
    """Return the Crr of a road surface; an unknown surface rolls like the default one."""
    return ROLLING_RESISTANCE_BY_SURFACE.get(surface, ROLLING_RESISTANCE_COEFFICIENT)


def resistive_force_newtons(
    speed_mps: float,
    grade_percent: float,
    total_mass_kg: float,
    *,
    rolling_resistance: float = ROLLING_RESISTANCE_COEFFICIENT,
    wind_resistance_kg_per_m: float = WIND_RESISTANCE_KG_PER_M,
) -> float:
    """Return the force opposing forward motion: gravity along the slope, rolling and air drag.

    Negative on a descent steep enough that gravity outweighs the other two.
    """
    slope_angle = math.atan(grade_percent / _PERCENT)
    weight = total_mass_kg * GRAVITY_MPS2
    gravity = weight * math.sin(slope_angle)
    rolling = weight * rolling_resistance * math.cos(slope_angle)
    drag = wind_resistance_kg_per_m * speed_mps * speed_mps
    return gravity + rolling + drag


def advance_speed(
    speed_mps: float,
    power_watts: float,
    grade_percent: float,
    total_mass_kg: float,
    dt_seconds: float,
    *,
    rolling_resistance: float = ROLLING_RESISTANCE_COEFFICIENT,
    wind_resistance_kg_per_m: float = WIND_RESISTANCE_KG_PER_M,
) -> float:
    """Return the bike's speed after riding *dt_seconds* at *power_watts* on *grade_percent*.

    The bike never rolls backwards: a rider who stops on a climb simply stops.
    """
    speed = max(0.0, float(speed_mps))
    remaining = max(0.0, float(dt_seconds))
    power = max(0.0, float(power_watts))
    while remaining > 0.0:
        step = min(remaining, _MAX_STEP_SECONDS)
        remaining -= step
        drive = power / max(speed, _MIN_DRIVE_SPEED_MPS)
        resistance = resistive_force_newtons(
            speed,
            grade_percent,
            total_mass_kg,
            rolling_resistance=rolling_resistance,
            wind_resistance_kg_per_m=wind_resistance_kg_per_m,
        )
        speed = max(0.0, speed + (drive - resistance) / total_mass_kg * step)
    return speed

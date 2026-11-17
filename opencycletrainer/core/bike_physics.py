from __future__ import annotations

import math

GRAVITY_MPS2 = 9.80665

ROLLING_RESISTANCE_COEFFICIENT = 0.004
"""Crr of a road tyre on asphalt (unitless)."""

WIND_RESISTANCE_KG_PER_M = 0.25
"""Cw = half air density x CdA, for a rider on the hoods at sea level (kg/m)."""

_PERCENT = 100.0
_MIN_DRIVE_SPEED_MPS = 1.0
"""Speed floor used when turning power into force, so a standing start is not infinite force."""

_MAX_STEP_SECONDS = 0.1
"""Longest single integration step; longer time spans are split into steps of this size."""


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

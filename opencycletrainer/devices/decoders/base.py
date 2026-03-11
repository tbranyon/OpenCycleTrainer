from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DecodedMetrics:
    power_watts: int | None = None
    cadence_rpm: float | None = None
    heart_rate_bpm: int | None = None
    speed_mps: float | None = None

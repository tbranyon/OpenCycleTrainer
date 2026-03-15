"""Workout summary data types and TSS computation."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WorkoutSummary:
    """Snapshot of metrics collected over a completed workout."""

    elapsed_seconds: float
    kj: float
    normalized_power: int | None
    tss: float | None
    avg_hr: int | None


def compute_tss(
    np_watts: int | None,
    ftp_watts: int,
    elapsed_seconds: float,
) -> float | None:
    """Compute Training Stress Score (TSS).

    TSS = (duration_s × NP × IF) / (FTP × 3600) × 100, where IF = NP / FTP.
    Returns None when inputs are insufficient to compute a meaningful score.
    """
    if np_watts is None or ftp_watts <= 0 or elapsed_seconds <= 0:
        return None
    intensity_factor = np_watts / ftp_watts
    return (elapsed_seconds * np_watts * intensity_factor) / (ftp_watts * 3600.0) * 100.0

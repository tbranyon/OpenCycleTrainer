from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from opencycletrainer.core.recorder import RecorderSample


@dataclass(frozen=True)
class WorkoutMetrics:
    """Metrics derived from a finalized 1 Hz sample stream."""

    avg_power_watts: float | None
    normalized_power: int | None
    tss: float | None
    avg_hr: int | None
    kj: float


def compute_workout_metrics(
    samples: list[RecorderSample],
    ftp_watts: int,
) -> WorkoutMetrics:
    """Compute summary metrics from a finalized list of 1 Hz recorder samples.

    Each sample represents exactly one second of recording time.  Effective power
    follows the bike-first, trainer-fallback policy used by the FIT exporter.
    TSS is None when *ftp_watts* is zero/negative or when NP cannot be determined.
    """
    effective_powers = [_effective_power(s) for s in samples]

    avg_power = _compute_avg_power(effective_powers)
    kj = _compute_kj(effective_powers)
    np_watts = _compute_np(effective_powers)
    avg_hr = _compute_avg_hr(samples)
    tss = _compute_tss(np_watts, ftp_watts, len(samples))

    return WorkoutMetrics(
        avg_power_watts=avg_power,
        normalized_power=np_watts,
        tss=tss,
        avg_hr=avg_hr,
        kj=kj,
    )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _effective_power(sample: RecorderSample) -> int | None:
    """Return the effective power for a sample: bike preferred, trainer fallback."""
    if sample.bike_power_watts is not None:
        return sample.bike_power_watts
    return sample.trainer_power_watts


def _compute_avg_power(effective_powers: list[int | None]) -> float | None:
    values = [p for p in effective_powers if p is not None]
    if not values:
        return None
    return sum(values) / len(values)


def _compute_kj(effective_powers: list[int | None]) -> float:
    """Sum effective power × 1 s per sample, convert to kJ."""
    return sum(p for p in effective_powers if p is not None) / 1000.0


def _compute_np(effective_powers: list[int | None]) -> int | None:
    """30-second rolling 4th-power mean of the 1 Hz effective power series.

    Samples with no power (None) are treated as 0 W, consistent with paused
    seconds being zero-power rather than missing from the series.
    Returns None when fewer than 30 samples are present.
    """
    n = len(effective_powers)
    if n < 30:
        return None

    # Replace None with 0 W (paused / no-signal seconds)
    pw = [float(p) if p is not None else 0.0 for p in effective_powers]

    window_sum = sum(pw[:30])
    fourth_powers = [(window_sum / 30.0) ** 4]
    for i in range(30, n):
        window_sum += pw[i] - pw[i - 30]
        fourth_powers.append((window_sum / 30.0) ** 4)

    return int(round((sum(fourth_powers) / len(fourth_powers)) ** 0.25))


def _compute_avg_hr(samples: list[RecorderSample]) -> int | None:
    values = [s.heart_rate_bpm for s in samples if s.heart_rate_bpm is not None]
    if not values:
        return None
    return round(sum(values) / len(values))


def _compute_tss(
    np_watts: int | None,
    ftp_watts: int,
    duration_seconds: int,
) -> float | None:
    """TSS = (duration_s × NP × IF) / (FTP × 3600) × 100, where IF = NP / FTP.

    Duration is the number of recorded (recording-active) seconds — i.e. the
    sample count, which excludes paused time.
    Returns None when inputs are insufficient.
    """
    if np_watts is None or ftp_watts <= 0 or duration_seconds <= 0:
        return None
    intensity_factor = np_watts / ftp_watts
    return (duration_seconds * np_watts * intensity_factor) / (ftp_watts * 3600.0) * 100.0

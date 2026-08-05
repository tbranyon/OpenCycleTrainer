"""DFA α1 pipeline: RR ring buffer, window selection, quality gate, ``DfaRecord``.

Ties the artifact corrector (``core/dfa/artifact.py``) and the DFA estimator
(``core/dfa/dfa.py``) together into a real-time pipeline: RR beats are ingested
cheaply into a ring buffer, and every ``RECOMPUTE_INTERVAL_SECONDS`` the latest
120 s window is artifact-corrected, scored for quality, and reduced to a single
``DfaRecord``. Qt-free, numpy-only, no I/O — see spec [0d]/[0b].
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import Enum
import math

import numpy as np

from .artifact import ALPHA as DEFAULT_ARTIFACT_ALPHA
from .artifact import BREAKDOWN_KEYS, correct_artifacts
from .dfa import DEFAULT_LAMBDA, DFA_SCALE_MAX, DFA_SCALE_MIN, compute_alpha1

# Analysis window and output cadence (Gronwald/Rogers protocol; spec [0]/[2]).
DFA_WINDOW_SECONDS = 120
DFA_WINDOW_MS = 120_000.0
RECOMPUTE_INTERVAL_SECONDS = 5.0

# Minimum corrected beats for a valid DFA window. Every scale 4..16 needs at
# least one box (N >= 16), but a single box per scale is too unstable to
# trust; 32 guarantees >= 2 boxes even at the largest scale (16) while still
# being reachable during a brief signal dropout. Typical full windows hold
# ~150-400 beats.
N_MIN = 32

# Signal-continuity guards. The ring buffer is trimmed and windowed in the beat
# domain — arrival times never affect which beats form a window — so these are
# the only things distinguishing a live window from a frozen or spliced one.

# No beat for this long means the strap has gone and the newest window no longer
# describes the present. Beats arrive at most ~1.5 s apart (40 bpm) plus
# notification batching and transport jitter, so this clears real cadence with
# room to spare.
RR_STALE_SECONDS = 5.0

# A batch whose beats account for this much less wall time than has actually
# elapsed means beats were lost in transit. In steady state the two are equal to
# within one RR plus jitter, because a strap emits every interval exactly once;
# a genuine dropout costs far more than the tolerance.
RR_GAP_TOLERANCE_SECONDS = 3.0

# Composite quality gate thresholds (spec [5d]).
ARTIFACT_FRACTION_POOR = 0.05
ARTIFACT_FRACTION_DEGRADED = 0.02
R2_POOR = 0.95
R2_DEGRADED = 0.97
MAX_RUN_POOR = 5
MAX_RUN_DEGRADED = 3


class SignalQuality(Enum):
    """Composite trust level for a DFA α1 window (spec [5d])."""

    GOOD = "good"
    DEGRADED = "degraded"
    POOR = "poor"
    INSUFFICIENT = "insufficient"


@dataclass(frozen=True)
class DfaRecord:
    """One DFA α1 output, emitted at most every ``RECOMPUTE_INTERVAL_SECONDS``.

    ``t`` is the monotonic clock value (seconds, matching ``power_history``/
    ``chart_history``/the workout controller's clock) at recompute time — not
    a wall-clock ``datetime``. ``alpha1`` is ``None`` whenever ``quality`` is
    ``POOR`` or ``INSUFFICIENT`` (never a silently-suppressed 0.0).
    """

    t: float
    alpha1: float | None
    mean_power_w: float | None
    hr_bpm: float | None
    rmssd_ms: float | None
    quality: SignalQuality
    artifact_fraction: float
    artifact_breakdown: dict[str, int]
    max_correction_run: int
    r2_loglog: float
    quality_reason: str


def compute_quality(
    artifact_fraction: float,
    r2_loglog: float,
    n: int,
    max_correction_run: int,
) -> SignalQuality:
    """Return the composite :class:`SignalQuality` for a window (spec [5d])."""
    if n < N_MIN:
        return SignalQuality.INSUFFICIENT
    if (
        artifact_fraction > ARTIFACT_FRACTION_POOR
        or r2_loglog < R2_POOR
        or max_correction_run > MAX_RUN_POOR
    ):
        return SignalQuality.POOR
    if (
        artifact_fraction > ARTIFACT_FRACTION_DEGRADED
        or r2_loglog < R2_DEGRADED
        or max_correction_run > MAX_RUN_DEGRADED
    ):
        return SignalQuality.DEGRADED
    return SignalQuality.GOOD


def _quality_reason(
    quality: SignalQuality,
    artifact_fraction: float,
    breakdown: dict[str, int],
    r2_loglog: float,
    max_correction_run: int,
) -> str:
    """Return the human-readable reason for a non-GOOD window (spec [5e]).

    Checks conditions in the spec's documented order and returns the first
    match. Only called for windows with a full buffer; the empty-buffer and
    still-filling cases are handled by the caller before a window exists.
    """
    if quality == SignalQuality.INSUFFICIENT:
        return "Insufficient data (window filling…)"
    if quality == SignalQuality.GOOD:
        return ""
    if artifact_fraction > ARTIFACT_FRACTION_DEGRADED:
        return f"High artifact rate ({artifact_fraction:.0%} corrected beats)"
    ectopic = breakdown.get("ectopic", 0)
    if ectopic > 0 and ectopic == max(breakdown.values()):
        return "Predominantly ectopic beats — check fatigue or strap"
    missed = breakdown.get("missed", 0)
    extra = breakdown.get("extra", 0)
    if missed or extra:
        return f"Strap contact: {missed} missed + {extra} extra beats"
    if r2_loglog < R2_DEGRADED:
        return f"Noisy scaling fit (R²={r2_loglog:.2f})"
    if max_correction_run > MAX_RUN_DEGRADED:
        return f"Long correction run ({max_correction_run} consecutive)"
    return ""


def _empty_breakdown() -> dict[str, int]:
    return {key: 0 for key in BREAKDOWN_KEYS}


class DfaPipeline:
    """RR ingest, windowing, and 5 s recompute scheduling for DFA α1.

    Beats are appended to a ring buffer trimmed to just over the analysis
    window; ``maybe_recompute`` enforces the output cadence, and ``recompute``
    does the (side-effect-free bar ``latest_record``) heavy lifting so it can
    later move onto a background thread without changing its contract
    (spec [0d]).
    """

    def __init__(
        self,
        power_source: Callable[[float], float | None] | None = None,
        lam: float = DEFAULT_LAMBDA,
        window_ms: float = DFA_WINDOW_MS,
        scale_min: int = DFA_SCALE_MIN,
        scale_max: int = DFA_SCALE_MAX,
        artifact_alpha: float = DEFAULT_ARTIFACT_ALPHA,
    ) -> None:
        self._power_source = power_source
        self._lam = lam
        self._window_ms = float(window_ms)
        self._scale_min = scale_min
        self._scale_max = scale_max
        self._artifact_alpha = artifact_alpha
        self._buffer: deque[tuple[float, float]] = deque()
        self._has_rr_ever = False
        self._latest_record: DfaRecord | None = None
        self._last_recompute_at: float | None = None
        self._last_ingest_at: float | None = None

    @property
    def latest_record(self) -> DfaRecord | None:
        return self._latest_record

    def ingest_rr(self, rr_intervals_ms: Sequence[float] | None, now: float) -> None:
        """Append newly-received RR beats (ms) to the ring buffer. Cheap.

        A batch carrying materially less beat time than the wall time elapsed
        since the previous batch means beats were lost in transit, so the buffer
        is dropped: beats either side of a dropout are individually normal and
        would otherwise be spliced into one nominal window spanning far more
        than ``window_ms`` of real time.
        """
        if not rr_intervals_ms:
            return
        covered_seconds = sum(rr_intervals_ms) / 1000.0
        if (
            self._last_ingest_at is not None
            and (now - self._last_ingest_at) - covered_seconds > RR_GAP_TOLERANCE_SECONDS
        ):
            self._buffer.clear()
        self._last_ingest_at = float(now)
        self._has_rr_ever = True
        for rr in rr_intervals_ms:
            self._buffer.append((float(now), float(rr)))
        self._trim_buffer()

    def maybe_recompute(self, now: float) -> DfaRecord | None:
        """Recompute if the 5 s output cadence has elapsed; else return ``None``.

        The first call always recomputes. Updates ``latest_record`` only when
        it actually recomputes.
        """
        if (
            self._last_recompute_at is not None
            and now - self._last_recompute_at < RECOMPUTE_INTERVAL_SECONDS
        ):
            return None
        self._last_recompute_at = now
        return self.recompute(now)

    def recompute(self, now: float) -> DfaRecord:
        """Select the latest window, score it, and return the new record.

        Side-effect-free apart from updating ``latest_record`` — safe to call
        directly (bypassing the cadence gate) and safe to move onto a
        background thread later.
        """
        window_rr = self._select_window(now)
        record = (
            self._insufficient_record(now)
            if window_rr is None
            else self._compute_record(now, window_rr)
        )
        self._latest_record = record
        return record

    def reset(self) -> None:
        """Clear the ring buffer and latest record (workout start/reset)."""
        self._buffer.clear()
        self._has_rr_ever = False
        self._latest_record = None
        self._last_recompute_at = None
        self._last_ingest_at = None

    def _trim_buffer(self) -> None:
        """Drop beats older than the beat that lands the buffer on the window boundary."""
        total = 0.0
        keep_from = 0
        buffer = self._buffer
        for i in range(len(buffer) - 1, -1, -1):
            total += buffer[i][1]
            if total >= self._window_ms:
                keep_from = i
                break
        for _ in range(keep_from):
            buffer.popleft()

    def _is_stale(self, now: float) -> bool:
        """True when the newest buffered beat is too old to describe the present."""
        if not self._buffer:
            return False
        return now - self._buffer[-1][0] > RR_STALE_SECONDS

    def _select_window(self, now: float) -> list[float] | None:
        """Walk backward from the newest beat accumulating rr_ms >= the window.

        Returns ``None`` when the buffer holds less than a full window, or when
        the newest beat is stale — beat-domain trimming alone would otherwise
        keep the last window selectable indefinitely after the strap drops.
        """
        if self._is_stale(now):
            return None
        total = 0.0
        idx = None
        buffer = self._buffer
        for i in range(len(buffer) - 1, -1, -1):
            total += buffer[i][1]
            if total >= self._window_ms:
                idx = i
                break
        if idx is None:
            return None
        return [rr for _, rr in list(buffer)[idx:]]

    def _insufficient_record(self, now: float) -> DfaRecord:
        if not self._has_rr_ever:
            reason = "No RR data from strap"
        elif self._is_stale(now):
            reason = "RR signal lost"
        else:
            reason = "Insufficient data (window filling…)"
        return DfaRecord(
            t=now,
            alpha1=None,
            mean_power_w=self._read_power(now),
            hr_bpm=None,
            rmssd_ms=None,
            quality=SignalQuality.INSUFFICIENT,
            artifact_fraction=0.0,
            artifact_breakdown=_empty_breakdown(),
            max_correction_run=0,
            r2_loglog=0.0,
            quality_reason=reason,
        )

    def _compute_record(self, now: float, window_rr: list[float]) -> DfaRecord:
        correction = correct_artifacts(window_rr, alpha=self._artifact_alpha)
        corrected_rr = correction.rr
        n = corrected_rr.shape[0]
        artifact_fraction = correction.corrected_count / n if n else 0.0

        hr_bpm = float(60_000.0 / np.mean(corrected_rr)) if n else None
        rmssd_ms = (
            float(np.sqrt(np.mean(np.diff(corrected_rr) ** 2))) if n >= 2 else None
        )

        alpha1_raw, r2_loglog_raw = compute_alpha1(
            corrected_rr,
            lam=self._lam,
            scale_min=self._scale_min,
            scale_max=self._scale_max,
        )
        r2_loglog = 0.0 if math.isnan(r2_loglog_raw) else r2_loglog_raw

        quality = compute_quality(
            artifact_fraction, r2_loglog, n, correction.max_correction_run
        )
        alpha1 = None
        if quality not in (SignalQuality.POOR, SignalQuality.INSUFFICIENT) and not math.isnan(
            alpha1_raw
        ):
            alpha1 = alpha1_raw

        return DfaRecord(
            t=now,
            alpha1=alpha1,
            mean_power_w=self._read_power(now),
            hr_bpm=hr_bpm,
            rmssd_ms=rmssd_ms,
            quality=quality,
            artifact_fraction=artifact_fraction,
            artifact_breakdown=dict(correction.breakdown),
            max_correction_run=correction.max_correction_run,
            r2_loglog=r2_loglog,
            quality_reason=_quality_reason(
                quality,
                artifact_fraction,
                correction.breakdown,
                r2_loglog,
                correction.max_correction_run,
            ),
        )

    def _read_power(self, now: float) -> float | None:
        if self._power_source is None:
            return None
        watts = self._power_source(now)
        return None if watts is None else float(watts)

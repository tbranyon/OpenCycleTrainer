"""RR-interval artifact correction for the DFA α1 pipeline.

Implements the adaptive beat classifier of Lipponen & Tarvainen (2019,
*J. Med. Eng. Technol.* 43(3):173–181) from the published equations only — a
time-varying threshold derived from the local quartile deviation of the
successive-difference series, combined with a median-deviation series, feeding a
decision tree that labels each beat as normal, ectopic, missed, extra, long or
short. A gross physiological gate (300–2000 ms) backs it up for impossible
values. Corrections follow the paper/protocol: missed beats are split, extra
beats merged, and ectopic/long/short beats replaced by a natural cubic-spline
interpolation through the surrounding normal beats.

numpy only — no scipy. All computation is float64 on the beat-indexed RR series.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum

import numpy as np

# Gross physiological plausibility bounds (ms). ~30–200 bpm. Beats strictly
# outside this range are impossible and corrected regardless of local statistics.
RR_MIN_MS = 300.0
RR_MAX_MS = 2000.0

# Adaptive-classifier constants (Lipponen & Tarvainen 2019).
ALPHA = 5.2  # quartile-deviation threshold scaling for both dRR and mRR series
ECTOPIC_C1 = 0.13  # slope of the ectopic decision line in the (drr, s12) subspace
ECTOPIC_C2 = 0.17  # offset of the ectopic decision line
MEDIAN_WINDOW = 11  # centered window for the local RR median
THRESHOLD_WINDOW = 91  # centered window for the quartile-deviation thresholds
DRR_UNIT = 1.0  # normalised dRR magnitude above which a beat is a candidate
MRR_UNIT = 3.0  # normalised mRR magnitude above which a beat is a candidate

# Gross-gate beats are typed by their ratio to the local median so the right
# correction action (split / merge / spline) is applied.
_GROSS_MISSED_RATIO = 1.5  # ≳1.5× median ⇒ a dropped beat ⇒ split
_GROSS_EXTRA_RATIO = 0.67  # ≲0.67× median ⇒ a spurious beat ⇒ merge

# Below this many beats the adaptive stage is skipped (only the gross gate runs);
# real windows hold ~150–400 beats so this only guards degenerate inputs.
_MIN_CLASSIFY_BEATS = 5

# Order of the artifact-breakdown keys (also the diagnostic categories surfaced
# in the UI tooltip).
BREAKDOWN_KEYS = ("missed", "extra", "ectopic", "long", "short")


class BeatClass(Enum):
    """Per-beat artifact classification."""

    NORMAL = "normal"
    ECTOPIC = "ectopic"
    MISSED = "missed"
    EXTRA = "extra"
    LONG = "long"
    SHORT = "short"


@dataclass(frozen=True)
class ArtifactCorrection:
    """Result of correcting an RR window.

    ``rr`` is the corrected beat-indexed series (length may differ from the input
    because missed beats add a beat and extra beats remove one). ``corrected`` is
    a boolean flag per output beat. ``breakdown`` counts artifact *events* per
    category (keys per ``BREAKDOWN_KEYS``); ``corrected_count`` is their sum.
    ``max_correction_run`` is the longest run of consecutive corrected output
    beats (a synthetic split spans two, so this flags partially-synthetic
    windows even when the overall fraction is low).
    """

    rr: np.ndarray
    corrected: np.ndarray
    breakdown: dict[str, int]
    corrected_count: int
    max_correction_run: int


def _rolling_median(values: np.ndarray, window: int) -> np.ndarray:
    """Centered rolling median; the window shrinks (is clipped) at the edges."""
    n = values.shape[0]
    half = window // 2
    out = np.empty(n, dtype=np.float64)
    for i in range(n):
        out[i] = np.median(values[max(0, i - half):min(n, i + half + 1)])
    return out


def _rolling_quartile_threshold(signal: np.ndarray, window: int, alpha: float) -> np.ndarray:
    """Time-varying threshold ``alpha · QD(|signal|)`` over a centered window.

    ``QD`` is the quartile deviation ``(Q3 − Q1) / 2`` of the absolute signal,
    a robust dispersion estimate that ignores the artifact spikes themselves
    (they sit in the extreme tail, beyond the quartiles).
    """
    magnitude = np.abs(signal)
    n = magnitude.shape[0]
    half = window // 2
    out = np.empty(n, dtype=np.float64)
    for i in range(n):
        segment = magnitude[max(0, i - half):min(n, i + half + 1)]
        q1, q3 = np.quantile(segment, (0.25, 0.75))
        out[i] = alpha * ((q3 - q1) / 2.0)
    return out


def _normalise(signal: np.ndarray, threshold: np.ndarray) -> np.ndarray:
    """Divide ``signal`` by ``threshold``; positions with a zero threshold → 0."""
    out = np.zeros_like(signal)
    nonzero = threshold > 0.0
    out[nonzero] = signal[nonzero] / threshold[nonzero]
    return out


def _subspace_inner(drr: np.ndarray) -> np.ndarray:
    """Subspace S12: the extreme of the two immediate neighbours of each beat.

    For a positive jump take the larger neighbour, for a negative jump the
    smaller — so a genuine ectopic (a jump immediately reversed) lands far from
    the origin while symmetric noise stays near it.
    """
    padded = np.pad(drr, 1, mode="reflect")
    n = drr.shape[0]
    out = np.empty(n, dtype=np.float64)
    for i in range(n):
        left, right = padded[i], padded[i + 2]
        out[i] = max(left, right) if drr[i] > 0.0 else min(left, right)
    return out


def _subspace_forward(drr: np.ndarray) -> np.ndarray:
    """Subspace S22: the extreme of the next two differences after each beat.

    A missed beat (big up-step) is followed by a big down-step and vice-versa;
    taking the opposite-signed extreme of the following two steps exposes that.
    """
    padded = np.pad(drr, (0, 2), mode="reflect")
    n = drr.shape[0]
    out = np.empty(n, dtype=np.float64)
    for i in range(n):
        nxt1, nxt2 = padded[i + 1], padded[i + 2]
        out[i] = min(nxt1, nxt2) if drr[i] >= 0.0 else max(nxt1, nxt2)
    return out


def _apply_gross_gate(rr: np.ndarray, medrr: np.ndarray, labels: list[BeatClass]) -> None:
    """Force a classification on any beat outside the plausibility bounds."""
    for i in range(rr.shape[0]):
        if RR_MIN_MS <= rr[i] <= RR_MAX_MS:
            continue
        ratio = rr[i] / medrr[i] if medrr[i] > 0.0 else (2.0 if rr[i] > RR_MAX_MS else 0.5)
        if ratio >= _GROSS_MISSED_RATIO:
            labels[i] = BeatClass.MISSED
        elif ratio <= _GROSS_EXTRA_RATIO:
            labels[i] = BeatClass.EXTRA
        else:
            labels[i] = BeatClass.LONG if rr[i] > medrr[i] else BeatClass.SHORT


def classify_beats(rr: Sequence[float], alpha: float = ALPHA) -> tuple[BeatClass, ...]:
    """Classify each RR interval (Lipponen–Tarvainen + gross gate).

    Returns a tuple of :class:`BeatClass`, one per input beat. ``alpha`` scales
    the adaptive thresholds; larger values relax correction (see the paper's
    note on cleaner data), defaulting to the published 5.2.
    """
    rr = np.asarray(rr, dtype=np.float64)
    n = rr.shape[0]
    labels = [BeatClass.NORMAL] * n
    if n == 0:
        return tuple(labels)

    medrr = _rolling_median(rr, MEDIAN_WINDOW)

    if n >= _MIN_CLASSIFY_BEATS:
        drr = np.empty(n, dtype=np.float64)
        drr[0] = 0.0
        drr[1:] = np.diff(rr)
        th1 = _rolling_quartile_threshold(drr, THRESHOLD_WINDOW, alpha)
        drr_n = _normalise(drr, th1)

        deviation = rr - medrr
        mrr = deviation.copy()
        mrr[mrr < 0.0] *= 2.0  # emphasise short (negative) deviations per the paper
        th2 = _rolling_quartile_threshold(mrr, THRESHOLD_WINDOW, alpha)
        mrr_n = _normalise(mrr, th2)

        s12 = _subspace_inner(drr_n)
        s22 = _subspace_forward(drr_n)

        for i in range(n):
            d = drr_n[i]
            if d > DRR_UNIT and s12[i] < -ECTOPIC_C1 * d - ECTOPIC_C2:
                labels[i] = BeatClass.ECTOPIC
                continue
            if d < -DRR_UNIT and s12[i] > -ECTOPIC_C1 * d + ECTOPIC_C2:
                labels[i] = BeatClass.ECTOPIC
                continue
            if abs(d) <= DRR_UNIT and abs(mrr_n[i]) <= MRR_UNIT:
                continue

            long_step = d > DRR_UNIT and s22[i] < -DRR_UNIT
            short_step = d < -DRR_UNIT and s22[i] > DRR_UNIT
            big_deviation = abs(mrr_n[i]) > MRR_UNIT
            if not (long_step or short_step or big_deviation):
                continue

            is_missed = abs(rr[i] / 2.0 - medrr[i]) < th2[i]
            is_extra = i + 1 < n and abs(rr[i] + rr[i + 1] - medrr[i]) < th2[i]
            if short_step and is_extra:
                labels[i] = BeatClass.EXTRA
            elif long_step and is_missed:
                labels[i] = BeatClass.MISSED
            else:
                labels[i] = BeatClass.LONG if deviation[i] > 0.0 else BeatClass.SHORT

    _apply_gross_gate(rr, medrr, labels)
    return tuple(labels)


class _NaturalCubicSpline:
    """Natural cubic spline through ``(x, y)`` anchors, solved with numpy only."""

    def __init__(self, x: np.ndarray, y: np.ndarray) -> None:
        self._x = np.asarray(x, dtype=np.float64)
        self._y = np.asarray(y, dtype=np.float64)
        m = self._x.shape[0]
        self._m2 = np.zeros(m, dtype=np.float64)  # second derivatives; natural ends = 0
        if m < 3:
            return
        h = np.diff(self._x)
        # Symmetric tridiagonal system for the interior second derivatives.
        lower = h[:-1]
        diag = 2.0 * (h[:-1] + h[1:])
        upper = h[1:]
        rhs = 6.0 * (np.diff(self._y[1:]) / h[1:] - np.diff(self._y[:-1]) / h[:-1])
        self._m2[1:-1] = _solve_tridiagonal(lower, diag, upper, rhs)

    def __call__(self, query: float) -> float:
        x, y, m2 = self._x, self._y, self._m2
        # Locate the interval, clamping queries outside the anchor span.
        j = int(np.clip(np.searchsorted(x, query) - 1, 0, x.shape[0] - 2))
        h = x[j + 1] - x[j]
        a = (x[j + 1] - query) / h
        b = (query - x[j]) / h
        value = (
            a * y[j]
            + b * y[j + 1]
            + ((a ** 3 - a) * m2[j] + (b ** 3 - b) * m2[j + 1]) * (h ** 2) / 6.0
        )
        return float(value)


def _solve_tridiagonal(
    lower: np.ndarray, diag: np.ndarray, upper: np.ndarray, rhs: np.ndarray
) -> np.ndarray:
    """Thomas algorithm for a tridiagonal system (O(n), no scipy)."""
    n = diag.shape[0]
    c = np.empty(n, dtype=np.float64)
    d = np.empty(n, dtype=np.float64)
    c[0] = upper[0] / diag[0]
    d[0] = rhs[0] / diag[0]
    for i in range(1, n):
        denom = diag[i] - lower[i - 1] * c[i - 1]
        c[i] = upper[i] / denom if i < n - 1 else 0.0
        d[i] = (rhs[i] - lower[i - 1] * d[i - 1]) / denom
    x = np.empty(n, dtype=np.float64)
    x[-1] = d[-1]
    for i in range(n - 2, -1, -1):
        x[i] = d[i] - c[i] * x[i + 1]
    return x


def _max_run(flags: list[bool]) -> int:
    """Longest run of consecutive ``True`` values."""
    best = run = 0
    for flag in flags:
        run = run + 1 if flag else 0
        best = max(best, run)
    return best


def correct_artifacts(rr: Sequence[float], alpha: float = ALPHA) -> ArtifactCorrection:
    """Classify and correct an RR window, returning the corrected series + metrics.

    Missed beats are split into two equal halves, extra beats merged with the
    following interval, and ectopic/long/short beats replaced by a natural
    cubic-spline value interpolated from the surrounding normal beats.
    """
    rr = np.asarray(rr, dtype=np.float64)
    n = rr.shape[0]
    labels = classify_beats(rr, alpha=alpha)
    medrr = _rolling_median(rr, MEDIAN_WINDOW) if n else np.empty(0)

    normal_idx = [i for i, label in enumerate(labels) if label == BeatClass.NORMAL]
    spline = (
        _NaturalCubicSpline(np.asarray(normal_idx, dtype=np.float64), rr[normal_idx])
        if len(normal_idx) >= 2
        else None
    )

    out_rr: list[float] = []
    out_flags: list[bool] = []
    breakdown = {key: 0 for key in BREAKDOWN_KEYS}
    consumed = np.zeros(n, dtype=bool)

    for i in range(n):
        if consumed[i]:
            continue
        label = labels[i]

        if label == BeatClass.NORMAL:
            out_rr.append(float(rr[i]))
            out_flags.append(False)
        elif label == BeatClass.MISSED:
            half = float(rr[i]) / 2.0
            out_rr.extend((half, half))
            out_flags.extend((True, True))
            breakdown["missed"] += 1
        elif label == BeatClass.EXTRA:
            if i + 1 < n and not consumed[i + 1]:
                out_rr.append(float(rr[i] + rr[i + 1]))
                out_flags.append(True)
                consumed[i + 1] = True
            elif out_rr:  # last beat: merge backwards into the previous interval
                out_rr[-1] += float(rr[i])
                out_flags[-1] = True
            else:
                out_rr.append(float(rr[i]))
                out_flags.append(True)
            breakdown["extra"] += 1
        else:  # ECTOPIC / LONG / SHORT -> spline interpolation from normal beats
            value = spline(float(i)) if spline is not None else float(medrr[i])
            out_rr.append(value)
            out_flags.append(True)
            breakdown[label.value] += 1

    corrected_count = sum(breakdown.values())
    return ArtifactCorrection(
        rr=np.asarray(out_rr, dtype=np.float64),
        corrected=np.asarray(out_flags, dtype=bool),
        breakdown=breakdown,
        corrected_count=corrected_count,
        max_correction_run=_max_run(out_flags),
    )

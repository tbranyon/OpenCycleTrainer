"""The fast DFA α1 code paths must reproduce the straightforward definitions.

The reference functions below are the original per-beat implementations, kept here as an
oracle. Artifact classification and correction must match them exactly; the banded detrend
must match the dense solve to floating-point precision.
"""

from __future__ import annotations

import numpy as np
import pytest

from opencycletrainer.core.dfa import artifact
from opencycletrainer.core.dfa.artifact import (
    ALPHA,
    BeatClass,
    DRR_UNIT,
    ECTOPIC_C1,
    ECTOPIC_C2,
    MEDIAN_WINDOW,
    MRR_UNIT,
    RR_MAX_MS,
    RR_MIN_MS,
    THRESHOLD_WINDOW,
    classify_beats,
    correct_artifacts,
)
from opencycletrainer.core.dfa.dfa import DEFAULT_LAMBDA, compute_alpha1, detrend_smoothness_priors

# ── Reference (original) implementations ──────────────────────────────────────


def _ref_rolling_median(values, window):
    n = values.shape[0]
    half = window // 2
    out = np.empty(n, dtype=np.float64)
    for i in range(n):
        out[i] = np.median(values[max(0, i - half):min(n, i + half + 1)])
    return out


def _ref_rolling_quartile_threshold(signal, window, alpha):
    magnitude = np.abs(signal)
    n = magnitude.shape[0]
    half = window // 2
    out = np.empty(n, dtype=np.float64)
    for i in range(n):
        q1, q3 = np.quantile(magnitude[max(0, i - half):min(n, i + half + 1)], (0.25, 0.75))
        out[i] = alpha * ((q3 - q1) / 2.0)
    return out


def _ref_normalise(signal, threshold):
    out = np.zeros_like(signal)
    nonzero = threshold > 0.0
    out[nonzero] = signal[nonzero] / threshold[nonzero]
    return out


def _ref_subspace_inner(drr):
    padded = np.pad(drr, 1, mode="reflect")
    out = np.empty(drr.shape[0])
    for i in range(drr.shape[0]):
        left, right = padded[i], padded[i + 2]
        out[i] = max(left, right) if drr[i] > 0.0 else min(left, right)
    return out


def _ref_subspace_forward(drr):
    padded = np.pad(drr, (0, 2), mode="reflect")
    out = np.empty(drr.shape[0])
    for i in range(drr.shape[0]):
        nxt1, nxt2 = padded[i + 1], padded[i + 2]
        out[i] = min(nxt1, nxt2) if drr[i] >= 0.0 else max(nxt1, nxt2)
    return out


def _ref_classify(rr, alpha=ALPHA):
    rr = np.asarray(rr, dtype=np.float64)
    n = rr.shape[0]
    labels = [BeatClass.NORMAL] * n
    if n == 0:
        return tuple(labels)
    medrr = _ref_rolling_median(rr, MEDIAN_WINDOW)
    if n >= 5:
        drr = np.empty(n)
        drr[0] = 0.0
        drr[1:] = np.diff(rr)
        th1 = _ref_rolling_quartile_threshold(drr, THRESHOLD_WINDOW, alpha)
        drr_n = _ref_normalise(drr, th1)
        deviation = rr - medrr
        mrr = deviation.copy()
        mrr[mrr < 0.0] *= 2.0
        th2 = _ref_rolling_quartile_threshold(mrr, THRESHOLD_WINDOW, alpha)
        mrr_n = _ref_normalise(mrr, th2)
        s12 = _ref_subspace_inner(drr_n)
        s22 = _ref_subspace_forward(drr_n)
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
    for i in range(n):
        if RR_MIN_MS <= rr[i] <= RR_MAX_MS:
            continue
        ratio = rr[i] / medrr[i] if medrr[i] > 0.0 else (2.0 if rr[i] > RR_MAX_MS else 0.5)
        if ratio >= 1.5:
            labels[i] = BeatClass.MISSED
        elif ratio <= 0.67:
            labels[i] = BeatClass.EXTRA
        else:
            labels[i] = BeatClass.LONG if rr[i] > medrr[i] else BeatClass.SHORT
    return tuple(labels)


def _ref_detrend_dense(z, lam=DEFAULT_LAMBDA):
    z = np.asarray(z, dtype=np.float64)
    n = z.shape[0]
    if n < 3:
        return z - z.mean() if n else z.copy()
    d2 = np.zeros((n - 2, n))
    rows = np.arange(n - 2)
    d2[rows, rows] = 1.0
    d2[rows, rows + 1] = -2.0
    d2[rows, rows + 2] = 1.0
    a = np.eye(n) + (lam ** 2) * (d2.T @ d2)
    return z - np.linalg.solve(a, z)


# ── Test windows ──────────────────────────────────────────────────────────────


def _window(n: int, seed: int, *, artifacts: bool) -> np.ndarray:
    rng = np.random.default_rng(seed)
    rr = 420.0 + 30.0 * np.sin(np.arange(n) / 7.0) + rng.normal(0.0, 9.0, n)
    if artifacts and n >= 12:
        idx = rng.choice(np.arange(2, n - 2), size=max(1, n // 25), replace=False)
        for k, i in enumerate(idx):
            kind = k % 5
            if kind == 0:
                rr[i] *= 1.95                 # missed beat
            elif kind == 1:
                rr[i] *= 0.5                  # extra beat
            elif kind == 2:
                rr[i] *= 0.7                  # premature (ectopic) beat...
                rr[i + 1] *= 1.3              # ...followed by compensatory pause
            elif kind == 3:
                rr[i] = 2500.0                # gross long outlier
            else:
                rr[i] = 150.0                 # gross short outlier
    return rr


_SIZES = (0, 1, 3, 5, 6, 11, 12, 45, 90, 91, 92, 150, 300, 400)
_CASES = [(n, seed, art) for n in _SIZES for seed in (1, 2) for art in (False, True)]


@pytest.mark.parametrize("n,seed,with_artifacts", _CASES)
def test_classification_matches_reference_exactly(n, seed, with_artifacts):
    rr = _window(n, seed, artifacts=with_artifacts)
    assert classify_beats(rr) == _ref_classify(rr)


@pytest.mark.parametrize("n,seed,with_artifacts", _CASES)
def test_correction_matches_reference_exactly(n, seed, with_artifacts):
    rr = _window(n, seed, artifacts=with_artifacts)
    result = correct_artifacts(rr)

    # Reference correction, built from the reference labels with the original algorithm.
    labels = _ref_classify(rr)
    medrr = _ref_rolling_median(rr, MEDIAN_WINDOW) if n else np.empty(0)
    normal_idx = [i for i, label in enumerate(labels) if label == BeatClass.NORMAL]
    spline = (
        artifact._NaturalCubicSpline(np.asarray(normal_idx, dtype=np.float64), rr[normal_idx])
        if len(normal_idx) >= 2 else None
    )
    out_rr, out_flags = [], []
    breakdown = {key: 0 for key in artifact.BREAKDOWN_KEYS}
    consumed = np.zeros(n, dtype=bool)
    for i in range(n):
        if consumed[i]:
            continue
        label = labels[i]
        if label == BeatClass.NORMAL:
            out_rr.append(float(rr[i])); out_flags.append(False)
        elif label == BeatClass.MISSED:
            out_rr.extend((rr[i] / 2.0, rr[i] / 2.0)); out_flags.extend((True, True)); breakdown["missed"] += 1
        elif label == BeatClass.EXTRA:
            if i + 1 < n and not consumed[i + 1]:
                out_rr.append(float(rr[i] + rr[i + 1])); out_flags.append(True); consumed[i + 1] = True
            elif out_rr:
                out_rr[-1] += float(rr[i]); out_flags[-1] = True
            else:
                out_rr.append(float(rr[i])); out_flags.append(True)
            breakdown["extra"] += 1
        else:
            out_rr.append(spline(float(i)) if spline is not None else float(medrr[i]))
            out_flags.append(True)
            breakdown[label.value] += 1

    assert np.array_equal(result.rr, np.asarray(out_rr, dtype=np.float64))
    assert np.array_equal(result.corrected, np.asarray(out_flags, dtype=bool))
    assert result.breakdown == breakdown
    assert result.corrected_count == sum(breakdown.values())


@pytest.mark.parametrize("n", (0, 1, 2, 3, 4, 5, 16, 150, 300, 400))
def test_detrend_matches_dense_solve(n):
    z = _window(n, 7, artifacts=False)
    got = detrend_smoothness_priors(z)
    want = _ref_detrend_dense(z)
    assert got.shape == want.shape
    # Both solves carry rounding error of ~1e-8 ms (the system's condition number is ~4e6);
    # agreement to 1e-7 ms is the floor either method can promise.
    assert np.allclose(got, want, rtol=1e-9, atol=1e-7)


@pytest.mark.parametrize("n", (150, 300, 400))
def test_alpha1_unchanged_by_banded_detrend(n):
    from opencycletrainer.core.dfa.dfa import dfa

    rr = correct_artifacts(_window(n, 11, artifacts=True)).rr
    alpha1, r2 = compute_alpha1(rr)
    ref_alpha1, ref_r2 = dfa(_ref_detrend_dense(rr))
    assert alpha1 == pytest.approx(ref_alpha1, abs=1e-9)
    assert r2 == pytest.approx(ref_r2, abs=1e-9)

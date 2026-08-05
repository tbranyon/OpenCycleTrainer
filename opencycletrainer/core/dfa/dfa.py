"""DFA α1 numerical core: smoothness-priors detrending + detrended fluctuation analysis.

Implemented from the published equations only (Peng et al. 1995; Tarvainen,
Ranta-aho & Karjalainen 2002) using numpy alone — no scipy. All computation is in
float64 and operates on the beat-indexed RR series (never time-resampled).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

import numpy as np

# Smoothness-priors regularisation strength (Tarvainen 2002). 500 is the
# Kubios/Gronwald protocol default that pins the high-pass cutoff.
DEFAULT_LAMBDA = 500.0

# DFA box sizes (inclusive). 4..16 is the definition of the short-term exponent α1.
DFA_SCALE_MIN = 4
DFA_SCALE_MAX = 16

# Detrending needs the second-difference operator, which requires at least 3 points.
_MIN_DETREND_LENGTH = 3


def _second_difference_operator(n: int) -> np.ndarray:
    """Return the (n-2)×n second-order difference operator D2 (rows ``[1, -2, 1]``)."""
    d2 = np.zeros((n - 2, n), dtype=np.float64)
    rows = np.arange(n - 2)
    d2[rows, rows] = 1.0
    d2[rows, rows + 1] = -2.0
    d2[rows, rows + 2] = 1.0
    return d2


def detrend_smoothness_priors(z: Sequence[float], lam: float = DEFAULT_LAMBDA) -> np.ndarray:
    """Return the stationary RR series after smoothness-priors detrending.

    Solves ``A · z_trend = z`` with ``A = I + λ² · D2ᵀD2`` (symmetric positive-
    definite, pentadiagonal) and returns ``z − z_trend``. The system is solved, not
    inverted; at the window sizes seen here (N ≈ 150–400) a dense float64 solve is
    exact and sub-millisecond.
    """
    z = np.asarray(z, dtype=np.float64)
    n = z.shape[0]
    if n < _MIN_DETREND_LENGTH:
        return z - z.mean() if n else z.copy()

    d2 = _second_difference_operator(n)
    a = np.eye(n, dtype=np.float64) + (lam ** 2) * (d2.T @ d2)
    z_trend = np.linalg.solve(a, z)
    return z - z_trend


def linear_regression(x: Sequence[float], y: Sequence[float]) -> tuple[float, float, float]:
    """Return ``(slope, intercept, r2)`` of the ordinary least-squares fit of y on x."""
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    x_mean = x.mean()
    y_mean = y.mean()
    dx = x - x_mean
    s_xx = np.sum(dx * dx)
    s_xy = np.sum(dx * (y - y_mean))
    slope = s_xy / s_xx
    intercept = y_mean - slope * x_mean
    y_hat = intercept + slope * x
    ss_res = np.sum((y - y_hat) ** 2)
    ss_tot = np.sum((y - y_mean) ** 2)
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    return float(slope), float(intercept), float(r2)


def dfa_fluctuations(
    series: Sequence[float],
    scales: Iterable[int],
) -> tuple[np.ndarray, np.ndarray]:
    """Return ``(scales_used, F)`` — RMS fluctuation F(n) per integer box size n.

    Boxes are forward and non-overlapping (classic Peng/Kubios convention,
    ``floor(N/n)`` boxes, trailing remainder unused), with an order-1 within-box
    detrend. Scales larger than the series (no full box) are skipped.
    """
    y = np.asarray(series, dtype=np.float64)
    profile = np.cumsum(y - y.mean())
    n_samples = profile.shape[0]

    used: list[int] = []
    fluct: list[float] = []
    for n in scales:
        num_boxes = n_samples // n
        if num_boxes < 1:
            continue
        boxes = profile[: num_boxes * n].reshape(num_boxes, n)
        fluct.append(_box_fluctuation(boxes, n))
        used.append(n)
    return np.asarray(used, dtype=np.int64), np.asarray(fluct, dtype=np.float64)


def _box_fluctuation(boxes: np.ndarray, n: int) -> float:
    """Return the RMS of order-1 detrend residuals across every box of length n."""
    x = np.arange(n, dtype=np.float64)
    x_mean = x.mean()
    dx = x - x_mean
    s_xx = np.sum(dx * dx)
    box_mean = boxes.mean(axis=1, keepdims=True)
    slope = (dx[None, :] * (boxes - box_mean)).sum(axis=1) / s_xx
    fit = (box_mean[:, 0] - slope * x_mean)[:, None] + slope[:, None] * x[None, :]
    mean_sq_resid = ((boxes - fit) ** 2).mean(axis=1)
    return float(np.sqrt(mean_sq_resid.mean()))


def dfa(
    series: Sequence[float],
    scale_min: int = DFA_SCALE_MIN,
    scale_max: int = DFA_SCALE_MAX,
) -> tuple[float, float]:
    """Return ``(alpha1, r2_loglog)`` from DFA over integer scales ``scale_min..scale_max``.

    α1 is the slope of log F(n) vs log n; ``r2_loglog`` is that regression's R²,
    an independent indicator of clean fractal scaling. Returns ``(nan, nan)`` if
    fewer than two scales have a full box.
    """
    scales = range(scale_min, scale_max + 1)
    used, fluct = dfa_fluctuations(series, scales)
    if used.shape[0] < 2 or np.any(fluct <= 0.0):
        return float("nan"), float("nan")
    slope, _, r2 = linear_regression(np.log(used), np.log(fluct))
    return slope, r2


def compute_alpha1(
    rr: Sequence[float],
    lam: float = DEFAULT_LAMBDA,
    scale_min: int = DFA_SCALE_MIN,
    scale_max: int = DFA_SCALE_MAX,
) -> tuple[float, float]:
    """Full estimator: smoothness-priors detrend the RR series, then DFA → ``(alpha1, r2)``."""
    z_stat = detrend_smoothness_priors(rr, lam=lam)
    return dfa(z_stat, scale_min=scale_min, scale_max=scale_max)

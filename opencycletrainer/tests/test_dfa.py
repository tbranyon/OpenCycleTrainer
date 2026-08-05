from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from opencycletrainer.core.dfa import dfa as dfa_module
from opencycletrainer.core.dfa.dfa import (
    DEFAULT_LAMBDA,
    DFA_SCALE_MAX,
    DFA_SCALE_MIN,
    compute_alpha1,
    detrend_smoothness_priors,
    dfa,
    dfa_fluctuations,
    linear_regression,
)


def _dense_smoothness_trend(z: np.ndarray, lam: float) -> np.ndarray:
    """Reference smoothness-priors trend via an explicit dense second-difference build."""
    z = np.asarray(z, dtype=np.float64)
    n = len(z)
    d2 = np.zeros((n - 2, n))
    for i in range(n - 2):
        d2[i, i] = 1.0
        d2[i, i + 1] = -2.0
        d2[i, i + 2] = 1.0
    a = np.eye(n) + (lam ** 2) * (d2.T @ d2)
    return np.linalg.solve(a, z)


class TestSmoothnessPriorsDetrend:
    def test_matches_dense_reference(self):
        rng = np.random.default_rng(123)
        z = rng.standard_normal(200) * 30.0 + 900.0
        ref_stat = z - _dense_smoothness_trend(z, DEFAULT_LAMBDA)
        got = detrend_smoothness_priors(z, lam=DEFAULT_LAMBDA)
        assert np.allclose(got, ref_stat, atol=1e-8, rtol=1e-6)

    def test_matches_dense_reference_nondefault_lambda(self):
        rng = np.random.default_rng(99)
        z = rng.standard_normal(150) * 12.0 + 800.0
        ref_stat = z - _dense_smoothness_trend(z, 200.0)
        got = detrend_smoothness_priors(z, lam=200.0)
        assert np.allclose(got, ref_stat, atol=1e-8, rtol=1e-6)

    def test_linear_trend_fully_removed(self):
        # A perfectly linear series has zero second difference, so the smoothness-
        # priors trend reproduces it exactly and the detrended series is ~0.
        z = np.linspace(800.0, 1000.0, 240)
        z_stat = detrend_smoothness_priors(z, lam=DEFAULT_LAMBDA)
        assert np.max(np.abs(z_stat)) < 1e-6

    def test_returns_float64_array_same_length(self):
        z = np.arange(50, dtype=float) + 500.0
        out = detrend_smoothness_priors(z)
        assert out.shape == (50,)
        assert out.dtype == np.float64


class TestLinearRegression:
    def test_perfect_line(self):
        x = np.array([1.0, 2.0, 3.0, 4.0])
        y = 2.0 * x - 1.0
        slope, intercept, r2 = linear_regression(x, y)
        assert slope == pytest.approx(2.0)
        assert intercept == pytest.approx(-1.0)
        assert r2 == pytest.approx(1.0)

    def test_known_scatter_hand_computed(self):
        # Hand-computed: slope=1.1, intercept=1.1, r2=1-2.70/8.75=0.6914285714
        x = np.array([0.0, 1.0, 2.0, 3.0])
        y = np.array([1.0, 3.0, 2.0, 5.0])
        slope, intercept, r2 = linear_regression(x, y)
        assert slope == pytest.approx(1.1)
        assert intercept == pytest.approx(1.1)
        assert r2 == pytest.approx(0.6914285714, abs=1e-9)


class TestDfaFluctuations:
    def test_uses_only_scales_with_a_full_box(self):
        # N=40 -> scales > 40 have no box; 4..16 all fit.
        y = np.random.default_rng(1).standard_normal(40)
        used, f = dfa_fluctuations(y, range(DFA_SCALE_MIN, DFA_SCALE_MAX + 1))
        assert list(used) == list(range(4, 17))
        assert np.all(f > 0)

    def test_skips_scales_larger_than_series(self):
        y = np.random.default_rng(1).standard_normal(10)
        used, _ = dfa_fluctuations(y, range(4, 17))
        # Only n in 4..10 yield a full box (10//n >= 1).
        assert list(used) == [4, 5, 6, 7, 8, 9, 10]


class TestDfaSyntheticExponents:
    def test_white_noise_alpha_near_half(self):
        rng = np.random.default_rng(42)
        alpha, r2 = dfa(rng.standard_normal(20000))
        # Theoretical white-noise alpha is 0.5; over the short scales 4..16 the
        # DFA1 estimator carries a known small positive bias (~0.58-0.60).
        assert 0.45 < alpha < 0.70
        assert r2 > 0.95

    def test_brownian_alpha_near_three_halves(self):
        rng = np.random.default_rng(42)
        brownian = np.cumsum(rng.standard_normal(20000))
        alpha, r2 = dfa(brownian)
        assert 1.35 < alpha < 1.65
        assert r2 > 0.95

    def test_white_noise_clearly_below_brownian(self):
        rng = np.random.default_rng(7)
        a_white, _ = dfa(rng.standard_normal(8000))
        a_brown, _ = dfa(np.cumsum(rng.standard_normal(8000)))
        assert a_brown - a_white > 0.7


class TestComputeAlpha1:
    def test_detrend_recovers_exponent_under_trend(self):
        rng = np.random.default_rng(7)
        n = 2000
        noise = rng.standard_normal(n)
        trend = 20.0 * np.sin(np.linspace(0, 2 * np.pi, n)) + np.linspace(0, 15, n)

        a_plain, _ = dfa(noise)
        a_with_detrend, _ = compute_alpha1(noise + trend)
        a_raw, _ = dfa(noise + trend)

        # Detrending pulls the trended estimate back toward the plain-noise value.
        assert abs(a_with_detrend - a_plain) < abs(a_raw - a_plain)
        assert 0.45 < a_with_detrend < 0.70

    def test_returns_alpha_and_r2(self):
        rng = np.random.default_rng(3)
        rr = 900.0 + rng.standard_normal(400) * 25.0
        alpha, r2 = compute_alpha1(rr)
        assert np.isfinite(alpha)
        assert 0.0 <= r2 <= 1.0


class TestNumpyOnly:
    def test_module_does_not_import_scipy(self):
        source = Path(dfa_module.__file__).read_text(encoding="utf-8")
        assert "import scipy" not in source
        assert "from scipy" not in source

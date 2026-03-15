"""Tests for WorkoutSummary data type and compute_tss helper."""
from __future__ import annotations

from opencycletrainer.core.workout_summary import compute_tss


# ---------------------------------------------------------------------------
# compute_tss
# ---------------------------------------------------------------------------


def test_compute_tss_returns_100_for_one_hour_at_ftp():
    """One hour at exactly FTP should yield TSS of 100."""
    ftp = 250
    result = compute_tss(np_watts=250, ftp_watts=ftp, elapsed_seconds=3600.0)
    assert result is not None
    assert abs(result - 100.0) < 0.01


def test_compute_tss_returns_50_for_half_hour_at_ftp():
    ftp = 250
    result = compute_tss(np_watts=250, ftp_watts=ftp, elapsed_seconds=1800.0)
    assert result is not None
    assert abs(result - 50.0) < 0.01


def test_compute_tss_scales_with_intensity():
    """Riding at 2× FTP for 1 hour should give TSS of 400."""
    ftp = 200
    result = compute_tss(np_watts=400, ftp_watts=ftp, elapsed_seconds=3600.0)
    assert result is not None
    assert abs(result - 400.0) < 0.01


def test_compute_tss_returns_none_when_np_is_none():
    assert compute_tss(np_watts=None, ftp_watts=250, elapsed_seconds=3600.0) is None


def test_compute_tss_returns_none_when_ftp_is_zero():
    assert compute_tss(np_watts=200, ftp_watts=0, elapsed_seconds=3600.0) is None


def test_compute_tss_returns_none_when_elapsed_is_zero():
    assert compute_tss(np_watts=200, ftp_watts=250, elapsed_seconds=0.0) is None

from __future__ import annotations

import dataclasses
from pathlib import Path

import numpy as np
import pytest

from opencycletrainer.core.dfa import pipeline as pipeline_module
from opencycletrainer.core.dfa.pipeline import (
    ARTIFACT_FRACTION_DEGRADED,
    ARTIFACT_FRACTION_POOR,
    DFA_WINDOW_MS,
    DFA_WINDOW_SECONDS,
    MAX_RUN_DEGRADED,
    MAX_RUN_POOR,
    N_MIN,
    R2_DEGRADED,
    R2_POOR,
    RECOMPUTE_INTERVAL_SECONDS,
    RR_GAP_TOLERANCE_SECONDS,
    RR_STALE_SECONDS,
    DfaPipeline,
    DfaRecord,
    SignalQuality,
    compute_quality,
)


def _baseline(n: int = 60, mean: float = 800.0, amp: float = 20.0, cycles: float = 3.0) -> np.ndarray:
    """Smooth sinusoidal RR baseline (ms) that the artifact classifier leaves untouched.

    Matches the helper proven artifact-free in tests/test_dfa_artifact.py
    (TestCorrectionActions.test_clean_series_is_returned_unchanged).
    """
    k = np.arange(n, dtype=np.float64)
    return mean + amp * np.sin(2.0 * np.pi * cycles * k / n)


def _exact_window_ms(rr) -> float:
    """Window size that forces the *entire* rr sequence to be selected as the window."""
    return float(sum(rr)) - 1.0


def _clean_rr(n: int, mean: float = 800.0, sd: float = 20.0, seed: int = 2024) -> list[float]:
    """Noisy-but-artifact-free RR series (ms) with genuine beat-to-beat variability.

    A constant series has zero fluctuation at every scale, so DFA returns NaN;
    anything asserting on α1 needs real variability. Note that white noise gives
    a wobbly log-log fit over only 13 scales, so R² lands anywhere in ~0.92-0.99
    depending on the seed — a test that needs ``alpha1 is not None`` must pin a
    seed verified to clear the R² gate rather than assume any seed will.
    """
    rng = np.random.default_rng(seed)
    return list(mean + rng.standard_normal(n) * sd)


def _stream(pipeline: DfaPipeline, rr_ms, start: float = 0.0, batch_seconds: float = 1.0) -> float:
    """Feed rr beats as a real strap would and return the final arrival time.

    Beats accumulate in wall-clock order and are delivered in notification
    batches roughly every ``batch_seconds``, so the beat time each batch carries
    matches the wall time since the previous batch — the steady state the
    dropout detector must never mistake for signal loss.
    """
    now = start
    next_notify = start + batch_seconds
    pending: list[float] = []
    for rr in rr_ms:
        now += rr / 1000.0
        pending.append(float(rr))
        if now >= next_notify:
            pipeline.ingest_rr(pending, now=now)
            pending = []
            next_notify = now + batch_seconds
    if pending:
        pipeline.ingest_rr(pending, now=now)
    return now


class TestModuleShape:
    def test_no_qt_import(self):
        source = Path(pipeline_module.__file__).read_text(encoding="utf-8")
        assert "PySide" not in source
        assert "PyQt" not in source

    def test_no_scipy_import(self):
        source = Path(pipeline_module.__file__).read_text(encoding="utf-8")
        assert "import scipy" not in source
        assert "from scipy" not in source

    def test_dfa_record_field_names(self):
        names = {f.name for f in dataclasses.fields(DfaRecord)}
        assert names == {
            "t",
            "alpha1",
            "mean_power_w",
            "hr_bpm",
            "rmssd_ms",
            "quality",
            "artifact_fraction",
            "artifact_breakdown",
            "max_correction_run",
            "r2_loglog",
            "quality_reason",
        }

    def test_dfa_record_is_frozen(self):
        record = DfaPipeline().recompute(0.0)
        with pytest.raises(dataclasses.FrozenInstanceError):
            record.alpha1 = 1.0  # type: ignore[misc]

    def test_signal_quality_members(self):
        assert SignalQuality.GOOD.value == "good"
        assert SignalQuality.DEGRADED.value == "degraded"
        assert SignalQuality.POOR.value == "poor"
        assert SignalQuality.INSUFFICIENT.value == "insufficient"


class TestBufferFilling:
    def test_below_window_is_insufficient(self):
        pipeline = DfaPipeline()
        pipeline.ingest_rr([800.0] * 50, now=0.0)  # 40_000 ms << DFA_WINDOW_MS
        record = pipeline.recompute(0.0)
        assert record.quality == SignalQuality.INSUFFICIENT
        assert record.quality_reason == "Insufficient data (window filling…)"
        assert record.alpha1 is None

    def test_reaching_window_selects_a_full_window(self):
        rr = [800.0] * 200  # 160_000 ms >= DFA_WINDOW_MS (120_000 ms)
        pipeline = DfaPipeline()
        pipeline.ingest_rr(rr, now=0.0)
        record = pipeline.recompute(0.0)
        assert record.quality != SignalQuality.INSUFFICIENT
        assert record.quality_reason != "Insufficient data (window filling…)"


class TestNoRrData:
    def test_no_rr_ever_reports_no_rr_reason(self):
        pipeline = DfaPipeline()
        record = pipeline.recompute(0.0)
        assert record.quality == SignalQuality.INSUFFICIENT
        assert record.quality_reason == "No RR data from strap"
        assert record.alpha1 is None

    def test_empty_and_none_ingest_are_tolerated(self):
        pipeline = DfaPipeline()
        pipeline.ingest_rr([], now=0.0)
        pipeline.ingest_rr(None, now=1.0)
        record = pipeline.recompute(1.0)
        assert record.quality_reason == "No RR data from strap"


class TestRecomputeCadence:
    def test_first_call_always_recomputes(self):
        pipeline = DfaPipeline()
        assert pipeline.maybe_recompute(0.0) is not None

    def test_second_call_within_5s_returns_none(self):
        pipeline = DfaPipeline()
        pipeline.maybe_recompute(0.0)
        assert pipeline.maybe_recompute(2.0) is None

    def test_call_at_5s_recomputes_again(self):
        pipeline = DfaPipeline()
        first = pipeline.maybe_recompute(0.0)
        second = pipeline.maybe_recompute(RECOMPUTE_INTERVAL_SECONDS)
        assert second is not None
        assert second is not first
        assert pipeline.latest_record is second


class TestComputeQualityDirect:
    def test_insufficient_below_n_min(self):
        assert compute_quality(0.0, 1.0, N_MIN - 1, 0) == SignalQuality.INSUFFICIENT

    def test_good_at_n_min_with_clean_metrics(self):
        assert compute_quality(0.0, 1.0, N_MIN, 0) == SignalQuality.GOOD

    def test_poor_artifact_fraction_above_threshold(self):
        assert compute_quality(ARTIFACT_FRACTION_POOR + 0.001, 1.0, 100, 0) == SignalQuality.POOR

    def test_artifact_fraction_at_poor_threshold_is_degraded_not_poor(self):
        assert compute_quality(ARTIFACT_FRACTION_POOR, 1.0, 100, 0) == SignalQuality.DEGRADED

    def test_poor_r2_below_threshold(self):
        assert compute_quality(0.0, R2_POOR - 0.001, 100, 0) == SignalQuality.POOR

    def test_r2_at_poor_threshold_is_degraded_not_poor(self):
        assert compute_quality(0.0, R2_POOR, 100, 0) == SignalQuality.DEGRADED

    def test_poor_max_run_above_threshold(self):
        assert compute_quality(0.0, 1.0, 100, MAX_RUN_POOR + 1) == SignalQuality.POOR

    def test_max_run_at_poor_threshold_is_degraded_not_poor(self):
        assert compute_quality(0.0, 1.0, 100, MAX_RUN_POOR) == SignalQuality.DEGRADED

    def test_degraded_artifact_fraction_above_threshold(self):
        assert compute_quality(ARTIFACT_FRACTION_DEGRADED + 0.001, 1.0, 100, 0) == SignalQuality.DEGRADED

    def test_artifact_fraction_at_degraded_threshold_is_good(self):
        assert compute_quality(ARTIFACT_FRACTION_DEGRADED, 1.0, 100, 0) == SignalQuality.GOOD

    def test_degraded_r2_below_threshold(self):
        assert compute_quality(0.0, R2_DEGRADED - 0.001, 100, 0) == SignalQuality.DEGRADED

    def test_r2_at_degraded_threshold_is_good(self):
        assert compute_quality(0.0, R2_DEGRADED, 100, 0) == SignalQuality.GOOD

    def test_degraded_max_run_above_threshold(self):
        assert compute_quality(0.0, 1.0, 100, MAX_RUN_DEGRADED + 1) == SignalQuality.DEGRADED

    def test_max_run_at_degraded_threshold_is_good(self):
        assert compute_quality(0.0, 1.0, 100, MAX_RUN_DEGRADED) == SignalQuality.GOOD


class TestQualityTransitions:
    def test_insufficient_then_poor_via_high_artifact_fraction(self):
        # A large, fixed RR magnitude means few beats are needed to fill the
        # window, so pick a window comfortably larger than N_MIN beats worth
        # of that magnitude, keeping the math exact in float64.
        bad_value = 2200.0  # > RR_MAX_MS (2000): every beat forces the gross gate.
        window_ms = N_MIN * bad_value

        pipeline = DfaPipeline(window_ms=window_ms)

        pipeline.ingest_rr([800.0] * 10, now=0.0)
        insufficient = pipeline.recompute(0.0)
        assert insufficient.quality == SignalQuality.INSUFFICIENT

        # Enough clean beats to fill (and overshoot) the window with headroom.
        clean_n = int(window_ms // 800.0) + 20
        pipeline.ingest_rr(list(_baseline(n=clean_n)), now=1.0)
        clean_record = pipeline.recompute(1.0)
        assert clean_record.quality != SignalQuality.INSUFFICIENT
        assert clean_record.alpha1 is not None

        # A burst of out-of-range beats, comfortably more than N_MIN, pushes
        # the trimmed window to be entirely bad beats.
        pipeline.ingest_rr([bad_value] * (N_MIN + 20), now=2.0)
        poor_record = pipeline.recompute(2.0)
        assert poor_record.quality == SignalQuality.POOR
        assert poor_record.alpha1 is None
        assert poor_record.artifact_fraction > ARTIFACT_FRACTION_POOR
        assert poor_record.quality_reason.startswith("High artifact rate")


class TestPowerSource:
    def test_mean_power_populated_from_injected_source(self):
        pipeline = DfaPipeline(power_source=lambda now: 215.0)
        record = pipeline.recompute(0.0)
        assert record.mean_power_w == pytest.approx(215.0)

    def test_mean_power_none_when_source_returns_none(self):
        pipeline = DfaPipeline(power_source=lambda now: None)
        record = pipeline.recompute(0.0)
        assert record.mean_power_w is None

    def test_mean_power_none_when_no_source_injected(self):
        pipeline = DfaPipeline()
        record = pipeline.recompute(0.0)
        assert record.mean_power_w is None


class TestAlpha1OnCleanSeries:
    def test_alpha1_is_plausible_and_quality_is_good(self):
        rng = np.random.default_rng(2024)
        rr = list(800.0 + rng.standard_normal(600) * 20.0)
        window_ms = _exact_window_ms(rr)

        pipeline = DfaPipeline(window_ms=window_ms)
        pipeline.ingest_rr(rr, now=0.0)
        record = pipeline.recompute(0.0)

        assert record.quality == SignalQuality.GOOD
        assert record.alpha1 is not None
        assert np.isfinite(record.alpha1)
        assert -0.5 < record.alpha1 < 2.0
        assert record.quality_reason == ""


class TestRmssdAndHrBpm:
    def test_matches_hand_computed_values_on_clean_series(self):
        rr = _baseline()  # proven artifact-free
        window_ms = _exact_window_ms(rr)

        pipeline = DfaPipeline(window_ms=window_ms)
        pipeline.ingest_rr(list(rr), now=0.0)
        record = pipeline.recompute(0.0)

        assert record.artifact_fraction == pytest.approx(0.0)
        expected_hr = 60_000.0 / np.mean(rr)
        expected_rmssd = np.sqrt(np.mean(np.diff(rr) ** 2))
        assert record.hr_bpm == pytest.approx(expected_hr, rel=1e-9)
        assert record.rmssd_ms == pytest.approx(expected_rmssd, rel=1e-9)


class TestSignalLoss:
    """A window must expire once the strap stops delivering beats.

    The buffer is trimmed in the beat domain, so without an explicit staleness
    check the newest window stays selectable forever and the tile/chart/FIT
    record keep reporting a frozen α1 long after the strap has gone.
    """

    def test_window_expires_once_beats_stop_arriving(self):
        pipeline = DfaPipeline()
        pipeline.ingest_rr(_clean_rr(200), now=100.0)

        live = pipeline.recompute(100.0)
        assert live.quality != SignalQuality.INSUFFICIENT
        assert live.alpha1 is not None

        stale = pipeline.recompute(100.0 + RR_STALE_SECONDS + 0.1)
        assert stale.quality == SignalQuality.INSUFFICIENT
        assert stale.alpha1 is None
        assert stale.quality_reason == "RR signal lost"

    def test_window_survives_up_to_the_staleness_threshold(self):
        pipeline = DfaPipeline()
        pipeline.ingest_rr(_clean_rr(200), now=100.0)
        record = pipeline.recompute(100.0 + RR_STALE_SECONDS)
        assert record.quality != SignalQuality.INSUFFICIENT
        assert record.alpha1 is not None

    def test_realistic_notification_cadence_never_goes_stale(self):
        # seed 10 is pinned: verified to clear the R² gate (0.988), so this is
        # the end-to-end proof that a streamed window yields a usable α1.
        pipeline = DfaPipeline()
        now = _stream(pipeline, _clean_rr(300, seed=10))
        record = pipeline.recompute(now)
        assert record.quality == SignalQuality.GOOD
        assert record.alpha1 is not None

    def test_low_heart_rate_cadence_never_goes_stale(self):
        # 40 bpm: 1.5 s between beats is the widest realistic notification gap.
        pipeline = DfaPipeline()
        now = _stream(pipeline, _clean_rr(120, mean=1500.0, sd=30.0))
        record = pipeline.recompute(now)
        assert record.quality != SignalQuality.INSUFFICIENT

    def test_stale_reason_differs_from_never_received_reason(self):
        pipeline = DfaPipeline()
        assert pipeline.recompute(0.0).quality_reason == "No RR data from strap"
        pipeline.ingest_rr(_clean_rr(200), now=0.0)
        assert pipeline.recompute(RR_STALE_SECONDS + 1.0).quality_reason == "RR signal lost"

    def test_reconnecting_strap_recovers_from_stale(self):
        pipeline = DfaPipeline()
        pipeline.ingest_rr(_clean_rr(200), now=0.0)
        assert pipeline.recompute(60.0).quality == SignalQuality.INSUFFICIENT

        now = _stream(pipeline, _clean_rr(200, seed=99), start=60.0)
        assert pipeline.recompute(now).quality != SignalQuality.INSUFFICIENT


class TestDropoutGap:
    """Beats either side of a dropout must not be spliced into one window.

    Window selection sums RR values, so pre- and post-dropout beats would
    otherwise sit adjacent in a nominal 120 s window that really spans far
    longer. The artifact corrector cannot catch this — the beats on both sides
    of the seam are individually normal.
    """

    def test_dropout_discards_pre_gap_beats(self):
        pipeline = DfaPipeline()
        now = _stream(pipeline, _clean_rr(200))
        assert pipeline.recompute(now).quality != SignalQuality.INSUFFICIENT

        pipeline.ingest_rr([800.0, 800.0], now=now + 30.0)
        record = pipeline.recompute(now + 30.0)
        assert record.quality == SignalQuality.INSUFFICIENT
        assert record.quality_reason == "Insufficient data (window filling…)"

    def test_window_refills_cleanly_after_a_dropout(self):
        pipeline = DfaPipeline()
        now = _stream(pipeline, _clean_rr(200))
        pipeline.ingest_rr([800.0, 800.0], now=now + 30.0)
        now = _stream(pipeline, _clean_rr(200, seed=5), start=now + 30.0)
        assert pipeline.recompute(now).quality != SignalQuality.INSUFFICIENT

    def test_steady_streaming_never_registers_a_gap(self):
        pipeline = DfaPipeline()
        now = _stream(pipeline, _clean_rr(400))
        assert pipeline.recompute(now).quality != SignalQuality.INSUFFICIENT

    def test_latency_jitter_within_tolerance_is_not_a_gap(self):
        pipeline = DfaPipeline()
        now = _stream(pipeline, _clean_rr(200))

        # One batch carrying 0.8 s of beats but delivered late — still under the
        # tolerance, so the accumulated window must survive.
        late_by = RR_GAP_TOLERANCE_SECONDS - 0.5
        pipeline.ingest_rr([800.0], now=now + 0.8 + late_by)
        record = pipeline.recompute(now + 0.8 + late_by)
        assert record.quality != SignalQuality.INSUFFICIENT

    def test_first_batch_after_reset_is_never_a_gap(self):
        pipeline = DfaPipeline()
        _stream(pipeline, _clean_rr(200))
        pipeline.reset()

        # A long wall-clock delay before the first post-reset batch must not be
        # read as a dropout against the pre-reset arrival time.
        now = _stream(pipeline, _clean_rr(200, seed=11), start=10_000.0)
        assert pipeline.recompute(now).quality != SignalQuality.INSUFFICIENT


class TestReset:
    def test_reset_clears_buffer_and_latest_record(self):
        pipeline = DfaPipeline()
        pipeline.ingest_rr([800.0] * 50, now=0.0)
        pipeline.recompute(0.0)
        assert pipeline.latest_record is not None

        pipeline.reset()
        assert pipeline.latest_record is None

        # Buffer and "ever received RR" flag are cleared too.
        record = pipeline.recompute(1.0)
        assert record.quality_reason == "No RR data from strap"

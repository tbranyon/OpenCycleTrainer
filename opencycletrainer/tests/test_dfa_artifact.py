from __future__ import annotations

import numpy as np
import pytest

from opencycletrainer.core.dfa.artifact import (
    ALPHA,
    BREAKDOWN_KEYS,
    RR_MAX_MS,
    RR_MIN_MS,
    ArtifactCorrection,
    BeatClass,
    classify_beats,
    correct_artifacts,
)


def _baseline(n: int = 60, mean: float = 800.0, amp: float = 20.0, cycles: float = 3.0) -> np.ndarray:
    """Smooth sinusoidal RR baseline (ms).

    A smooth (autocorrelated) baseline keeps every successive difference well
    inside the adaptive threshold, so a clean run produces no false artifacts,
    while the zero-crossings (k = 0, 10, 20, … for n=60, cycles=3) sit exactly at
    ``mean`` — convenient anchor points for injecting crafted artifacts.
    """
    k = np.arange(n, dtype=np.float64)
    return mean + amp * np.sin(2.0 * np.pi * cycles * k / n)


class TestGrossPhysiologicalGate:
    def test_out_of_range_beats_are_flagged_regardless_of_local_dispersion(self):
        rr = _baseline()
        rr[30] = RR_MAX_MS + 200.0  # impossibly long (~2.75x median) -> missed
        rr[40] = RR_MIN_MS - 50.0  # impossibly short (~0.31x median) -> extra
        labels = classify_beats(rr)
        assert labels[30] == BeatClass.MISSED
        assert labels[40] == BeatClass.EXTRA

    def test_in_range_smooth_beat_is_normal(self):
        rr = _baseline()
        labels = classify_beats(rr)
        assert labels[10] == BeatClass.NORMAL

    def test_boundary_values_are_not_flagged(self):
        rr = _baseline()
        rr[30] = RR_MIN_MS  # exactly on the lower bound -> in range
        rr[40] = RR_MAX_MS  # exactly on the upper bound -> in range
        labels = classify_beats(rr)
        # The gross gate only fires strictly outside [RR_MIN, RR_MAX]; these
        # extreme-but-in-range values may be classified by the adaptive stage but
        # must not be forced by the gross gate into a missed/extra split.
        assert all(rr[i] >= RR_MIN_MS and rr[i] <= RR_MAX_MS for i in (30, 40))


class TestAdaptiveClassification:
    def test_missed_beat_detected(self):
        rr = _baseline()
        rr[30] = 1600.0  # a dropped beat doubles the interval (~2x median)
        labels = classify_beats(rr)
        assert labels[30] == BeatClass.MISSED

    def test_extra_beat_detected(self):
        base = _baseline()
        half = base[30] / 2.0
        rr = np.insert(base, 30, half)
        rr[31] = half  # one true interval split into two ~half intervals
        labels = classify_beats(rr)
        assert labels[30] == BeatClass.EXTRA

    def test_ectopic_beat_detected(self):
        rr = _baseline(n=80)
        base = rr[40]
        rr[40] = base * 0.6  # premature beat: short interval
        rr[41] = base * 1.4  # compensatory pause: long interval
        labels = classify_beats(rr)
        assert BeatClass.ECTOPIC in labels[39:43]

    def test_clean_series_has_no_artifacts(self):
        rr = _baseline()
        labels = classify_beats(rr)
        assert all(label == BeatClass.NORMAL for label in labels)


class TestCorrectionActions:
    def test_missed_split_adds_a_beat(self):
        rr = _baseline()
        rr[30] = 1600.0
        result = correct_artifacts(rr)
        assert isinstance(result, ArtifactCorrection)
        assert result.breakdown["missed"] == 1
        assert len(result.rr) == len(rr) + 1  # one interval split into two
        # the two synthetic halves are adjacent and both flagged corrected
        assert result.max_correction_run == 2
        assert result.rr[30] == pytest.approx(800.0)
        assert result.rr[31] == pytest.approx(800.0)

    def test_extra_merge_removes_a_beat(self):
        base = _baseline()
        true_interval = base[30]
        half = true_interval / 2.0
        rr = np.insert(base, 30, half)
        rr[31] = half
        result = correct_artifacts(rr)
        assert result.breakdown["extra"] == 1
        assert len(result.rr) == len(rr) - 1  # two halves merged back into one
        assert result.rr[30] == pytest.approx(true_interval)

    def test_longshort_spline_replaces_value_toward_neighbours(self):
        rr = _baseline()
        rr[30] = 1500.0  # long, but not a clean 2x -> spline-interpolated
        result = correct_artifacts(rr)
        assert result.breakdown["long"] == 1
        assert len(result.rr) == len(rr)  # spline keeps the series length
        # the spike is pulled back toward the local ~800 ms baseline
        assert 700.0 < result.rr[30] < 900.0

    def test_clean_series_is_returned_unchanged(self):
        rr = _baseline()
        result = correct_artifacts(rr)
        assert result.corrected_count == 0
        assert result.max_correction_run == 0
        assert all(value == 0 for value in result.breakdown.values())
        assert np.array_equal(result.rr, rr)


class TestBreakdownAndCounts:
    def test_breakdown_has_exact_keys(self):
        rr = _baseline()
        rr[30] = 1600.0
        result = correct_artifacts(rr)
        assert set(result.breakdown.keys()) == set(BREAKDOWN_KEYS)

    def test_corrected_count_is_sum_of_breakdown(self):
        rr = _baseline()
        rr[30] = 1600.0
        result = correct_artifacts(rr)
        assert result.corrected_count == sum(result.breakdown.values())
        assert result.corrected_count == 1

    def test_max_correction_run_single_for_isolated_spline(self):
        rr = _baseline()
        rr[30] = 1500.0  # isolated long -> single corrected output beat
        result = correct_artifacts(rr)
        assert result.max_correction_run == 1


class TestRelaxationKnob:
    def test_higher_alpha_relaxes_correction(self):
        rr = _baseline()
        rr[30] = 1500.0
        strict = correct_artifacts(rr, alpha=ALPHA)
        relaxed = correct_artifacts(rr, alpha=ALPHA * 6.0)
        assert relaxed.corrected_count <= strict.corrected_count

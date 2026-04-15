from __future__ import annotations

import pytest

from opencycletrainer.core.power_history import PowerHistory


class TestPowerHistoryDefaults:
    def test_workout_avg_watts_none_when_empty(self):
        ph = PowerHistory()
        assert ph.workout_avg_watts() is None

    def test_workout_actual_kj_zero_when_empty(self):
        ph = PowerHistory()
        assert ph.workout_actual_kj() == 0.0

    def test_windowed_avg_none_when_empty(self):
        ph = PowerHistory()
        assert ph.windowed_avg(now=100.0, window_seconds=30) is None

    def test_compute_normalized_power_none_when_empty(self):
        ph = PowerHistory()
        assert ph.compute_normalized_power() is None

    def test_as_series_empty(self):
        ph = PowerHistory()
        assert ph.as_series() == []


class TestPowerHistoryRecord:
    def test_single_sample_appears_in_series(self):
        ph = PowerHistory()
        ph.record(200, now=10.0, recording_active=False)
        assert ph.as_series() == [(10.0, 200)]

    def test_multiple_samples_ordered_in_series(self):
        ph = PowerHistory()
        ph.record(100, now=1.0, recording_active=False)
        ph.record(200, now=2.0, recording_active=False)
        ph.record(300, now=3.0, recording_active=False)
        assert ph.as_series() == [(1.0, 100), (2.0, 200), (3.0, 300)]

    def test_watts_coerced_to_int(self):
        ph = PowerHistory()
        ph.record(150, now=5.0, recording_active=False)
        series = ph.as_series()
        assert isinstance(series[0][1], int)

    def test_workout_avg_accumulates(self):
        ph = PowerHistory()
        ph.record(100, now=1.0, recording_active=False)
        ph.record(200, now=2.0, recording_active=False)
        assert ph.workout_avg_watts() == 150

    def test_kj_not_accumulated_when_recording_inactive(self):
        ph = PowerHistory()
        ph.record(200, now=1.0, recording_active=False)
        ph.record(200, now=2.0, recording_active=False)
        assert ph.workout_actual_kj() == 0.0

    def test_kj_accumulated_when_recording_active(self):
        ph = PowerHistory()
        ph.record(1000, now=0.0, recording_active=True)
        ph.record(1000, now=1.0, recording_active=True)
        # 1000 W * 1 s / 1000 = 1.0 kJ
        assert ph.workout_actual_kj() == pytest.approx(1.0)

    def test_kj_uses_delta_from_previous_tick(self):
        ph = PowerHistory()
        # First tick establishes baseline; no kJ yet
        ph.record(500, now=10.0, recording_active=True)
        assert ph.workout_actual_kj() == 0.0
        # Second tick: 500 W * 2 s = 1.0 kJ
        ph.record(500, now=12.0, recording_active=True)
        assert ph.workout_actual_kj() == pytest.approx(1.0)

    def test_kj_not_accumulated_for_first_tick(self):
        """No kJ on the very first record call since there's no prior tick."""
        ph = PowerHistory()
        ph.record(10000, now=0.0, recording_active=True)
        assert ph.workout_actual_kj() == 0.0

    def test_kj_switches_off_mid_workout(self):
        ph = PowerHistory()
        ph.record(1000, now=0.0, recording_active=True)
        ph.record(1000, now=1.0, recording_active=True)   # +1.0 kJ
        ph.record(1000, now=2.0, recording_active=False)  # not counted
        assert ph.workout_actual_kj() == pytest.approx(1.0)


class TestWindowedAvg:
    def test_all_samples_in_window(self):
        ph = PowerHistory()
        ph.record(100, now=0.0, recording_active=False)
        ph.record(200, now=1.0, recording_active=False)
        assert ph.windowed_avg(now=5.0, window_seconds=10) == 150

    def test_stale_samples_excluded(self):
        ph = PowerHistory()
        ph.record(100, now=0.0, recording_active=False)
        ph.record(300, now=20.0, recording_active=False)
        # At now=25 with window=10: only sample at t=20 is in window
        assert ph.windowed_avg(now=25.0, window_seconds=10) == 300

    def test_no_in_window_samples_returns_none(self):
        ph = PowerHistory()
        ph.record(200, now=0.0, recording_active=False)
        assert ph.windowed_avg(now=100.0, window_seconds=5) is None

    def test_window_boundary_inclusive(self):
        ph = PowerHistory()
        ph.record(200, now=90.0, recording_active=False)  # exactly at cutoff
        assert ph.windowed_avg(now=100.0, window_seconds=10) == 200


class TestWorkoutAvgWatts:
    def test_returns_none_with_no_data(self):
        ph = PowerHistory()
        assert ph.workout_avg_watts() is None

    def test_rounds_correctly(self):
        ph = PowerHistory()
        ph.record(100, now=1.0, recording_active=False)
        ph.record(101, now=2.0, recording_active=False)
        ph.record(102, now=3.0, recording_active=False)
        # avg = 303 / 3 = 101
        assert ph.workout_avg_watts() == 101


class TestNormalizedPower:
    def test_returns_none_with_single_sample(self):
        ph = PowerHistory()
        ph.record(200, now=0.0, recording_active=False)
        assert ph.compute_normalized_power() is None

    def test_returns_none_when_span_under_30s(self):
        ph = PowerHistory()
        for i in range(20):
            ph.record(200, now=float(i), recording_active=False)
        assert ph.compute_normalized_power() is None

    def test_returns_value_with_sufficient_data(self):
        ph = PowerHistory()
        # 60 seconds of steady 200 W — NP should be close to 200
        for i in range(60):
            ph.record(200, now=float(i), recording_active=False)
        np = ph.compute_normalized_power()
        assert np is not None
        assert isinstance(np, int)
        assert 195 <= np <= 205  # allow small rounding tolerance

    def test_np_higher_for_variable_power(self):
        """NP > avg for burst power due to fourth-power weighting.

        30 s at 100 W followed by 30 s at 300 W gives avg = 200 W but
        NP > 200 W because the 30 s rolling window averages are bimodal
        and the fourth-power mean is dominated by the high-power block.
        """
        ph = PowerHistory()
        for i in range(30):
            ph.record(100, now=float(i), recording_active=False)
        for i in range(30, 60):
            ph.record(300, now=float(i), recording_active=False)
        np = ph.compute_normalized_power()
        avg = ph.workout_avg_watts()
        assert np is not None and avg is not None
        assert np > avg


class TestReset:
    def test_reset_clears_series(self):
        ph = PowerHistory()
        ph.record(200, now=1.0, recording_active=True)
        ph.reset()
        assert ph.as_series() == []

    def test_reset_clears_kj(self):
        ph = PowerHistory()
        ph.record(1000, now=0.0, recording_active=True)
        ph.record(1000, now=1.0, recording_active=True)
        ph.reset()
        assert ph.workout_actual_kj() == 0.0

    def test_reset_clears_avg_watts(self):
        ph = PowerHistory()
        ph.record(200, now=1.0, recording_active=False)
        ph.reset()
        assert ph.workout_avg_watts() is None

    def test_reset_clears_windowed_avg(self):
        ph = PowerHistory()
        ph.record(200, now=1.0, recording_active=False)
        ph.reset()
        assert ph.windowed_avg(now=2.0, window_seconds=10) is None

    def test_kj_does_not_accumulate_across_reset(self):
        """No kJ on the first tick after reset (no prior tick baseline)."""
        ph = PowerHistory()
        ph.record(1000, now=0.0, recording_active=True)
        ph.record(1000, now=1.0, recording_active=True)
        ph.reset()
        ph.record(1000, now=10.0, recording_active=True)
        assert ph.workout_actual_kj() == 0.0

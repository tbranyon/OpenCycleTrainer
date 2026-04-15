from __future__ import annotations

import pytest

from opencycletrainer.core.interval_stats import IntervalStats


class TestIntervalStatsDefaults:
    def test_interval_avg_watts_none_when_empty(self):
        s = IntervalStats()
        assert s.interval_avg_watts() is None

    def test_interval_actual_kj_zero_when_empty(self):
        s = IntervalStats()
        assert s.interval_actual_kj() == 0.0

    def test_interval_avg_hr_none_when_empty(self):
        s = IntervalStats()
        assert s.interval_avg_hr() is None

    def test_workout_avg_hr_none_when_empty(self):
        s = IntervalStats()
        assert s.workout_avg_hr() is None


class TestIntervalStatsPower:
    def test_single_power_sample_sets_avg(self):
        s = IntervalStats()
        s.record_power(200, now=1.0, recording_active=False)
        assert s.interval_avg_watts() == 200

    def test_interval_avg_rounds(self):
        s = IntervalStats()
        s.record_power(100, now=1.0, recording_active=False)
        s.record_power(101, now=2.0, recording_active=False)
        s.record_power(102, now=3.0, recording_active=False)
        assert s.interval_avg_watts() == 101

    def test_kj_not_accumulated_when_recording_inactive(self):
        s = IntervalStats()
        s.record_power(1000, now=0.0, recording_active=False)
        s.record_power(1000, now=1.0, recording_active=False)
        assert s.interval_actual_kj() == 0.0

    def test_kj_accumulated_when_recording_active(self):
        s = IntervalStats()
        s.record_power(1000, now=0.0, recording_active=True)
        s.record_power(1000, now=1.0, recording_active=True)
        # 1000 W * 1 s / 1000 = 1.0 kJ
        assert s.interval_actual_kj() == pytest.approx(1.0)

    def test_kj_not_accumulated_for_first_tick(self):
        """No kJ on the very first record_power call since there's no prior tick."""
        s = IntervalStats()
        s.record_power(10000, now=0.0, recording_active=True)
        assert s.interval_actual_kj() == 0.0

    def test_kj_uses_delta_from_previous_tick(self):
        s = IntervalStats()
        s.record_power(500, now=10.0, recording_active=True)
        assert s.interval_actual_kj() == 0.0
        # 500 W * 2 s = 1.0 kJ
        s.record_power(500, now=12.0, recording_active=True)
        assert s.interval_actual_kj() == pytest.approx(1.0)

    def test_kj_not_counted_when_recording_turns_off(self):
        s = IntervalStats()
        s.record_power(1000, now=0.0, recording_active=True)
        s.record_power(1000, now=1.0, recording_active=True)  # +1.0 kJ
        s.record_power(1000, now=2.0, recording_active=False)  # not counted
        assert s.interval_actual_kj() == pytest.approx(1.0)


class TestIntervalStatsHR:
    def test_single_hr_sample_sets_interval_avg(self):
        s = IntervalStats()
        s.record_hr(150)
        assert s.interval_avg_hr() == 150

    def test_single_hr_sample_sets_workout_avg(self):
        s = IntervalStats()
        s.record_hr(150)
        assert s.workout_avg_hr() == 150

    def test_hr_accumulates_at_both_scopes(self):
        s = IntervalStats()
        s.record_hr(100)
        s.record_hr(200)
        assert s.interval_avg_hr() == 150
        assert s.workout_avg_hr() == 150

    def test_hr_rounds_correctly(self):
        s = IntervalStats()
        s.record_hr(149)
        s.record_hr(150)
        # avg = 149.5, rounds to 150
        assert s.interval_avg_hr() == 150


class TestIntervalStatsResetInterval:
    def test_reset_interval_clears_power_avg(self):
        s = IntervalStats()
        s.record_power(300, now=1.0, recording_active=True)
        s.reset_interval()
        assert s.interval_avg_watts() is None

    def test_reset_interval_clears_kj(self):
        s = IntervalStats()
        s.record_power(1000, now=0.0, recording_active=True)
        s.record_power(1000, now=1.0, recording_active=True)
        s.reset_interval()
        assert s.interval_actual_kj() == 0.0

    def test_reset_interval_clears_interval_hr_avg(self):
        s = IntervalStats()
        s.record_hr(160)
        s.reset_interval()
        assert s.interval_avg_hr() is None

    def test_reset_interval_preserves_workout_hr(self):
        s = IntervalStats()
        s.record_hr(160)
        s.reset_interval()
        # workout-level HR should survive interval reset
        assert s.workout_avg_hr() == 160

    def test_kj_does_not_carry_over_across_interval_reset(self):
        """No kJ on first tick after reset — tick baseline is cleared."""
        s = IntervalStats()
        s.record_power(1000, now=0.0, recording_active=True)
        s.record_power(1000, now=1.0, recording_active=True)
        s.reset_interval()
        s.record_power(1000, now=10.0, recording_active=True)
        assert s.interval_actual_kj() == 0.0


class TestIntervalStatsResetWorkout:
    def test_reset_workout_clears_power_avg(self):
        s = IntervalStats()
        s.record_power(300, now=1.0, recording_active=False)
        s.reset_workout()
        assert s.interval_avg_watts() is None

    def test_reset_workout_clears_kj(self):
        s = IntervalStats()
        s.record_power(1000, now=0.0, recording_active=True)
        s.record_power(1000, now=1.0, recording_active=True)
        s.reset_workout()
        assert s.interval_actual_kj() == 0.0

    def test_reset_workout_clears_interval_hr(self):
        s = IntervalStats()
        s.record_hr(150)
        s.reset_workout()
        assert s.interval_avg_hr() is None

    def test_reset_workout_clears_workout_hr(self):
        s = IntervalStats()
        s.record_hr(150)
        s.reset_workout()
        assert s.workout_avg_hr() is None

    def test_workout_hr_accumulates_across_intervals(self):
        s = IntervalStats()
        s.record_hr(100)
        s.reset_interval()
        s.record_hr(200)
        # Both readings count toward workout avg
        assert s.workout_avg_hr() == 150

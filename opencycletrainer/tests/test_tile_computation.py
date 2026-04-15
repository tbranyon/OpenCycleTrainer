from __future__ import annotations

import pytest

from opencycletrainer.core.workout_engine import EngineState, WorkoutEngineSnapshot
from opencycletrainer.storage.settings import AppSettings
from opencycletrainer.ui.tile_computation import TileComputation


def _make_snapshot() -> WorkoutEngineSnapshot:
    return WorkoutEngineSnapshot(
        state=EngineState.RUNNING,
        elapsed_seconds=10.0,
        riding_elapsed_seconds=10.0,
        total_duration_seconds=600,
        current_interval_index=0,
        current_interval_elapsed_seconds=10.0,
        current_interval_remaining_seconds=590.0,
        ramp_in_remaining_seconds=0.0,
        recording_active=False,
        pending_kj_extension=0,
    )


class _MockPowerHistory:
    def __init__(
        self,
        windowed=None,
        workout_avg=None,
        normalized=None,
        workout_kj=0.0,
    ):
        self._windowed = windowed
        self._workout_avg = workout_avg
        self._normalized = normalized
        self._workout_kj = workout_kj

    def windowed_avg(self, now: float, window_seconds: int):
        return self._windowed

    def workout_avg_watts(self):
        return self._workout_avg

    def compute_normalized_power(self):
        return self._normalized

    def workout_actual_kj(self) -> float:
        return self._workout_kj


class _MockCadenceHistory:
    def __init__(self, windowed=None):
        self._windowed = windowed

    def windowed_avg(self, now: float):
        return self._windowed


class _MockIntervalStats:
    def __init__(
        self,
        interval_avg=None,
        interval_kj=0.0,
        interval_avg_hr=None,
        workout_avg_hr=None,
    ):
        self._interval_avg = interval_avg
        self._interval_kj = interval_kj
        self._interval_avg_hr = interval_avg_hr
        self._workout_avg_hr = workout_avg_hr

    def interval_avg_watts(self):
        return self._interval_avg

    def interval_actual_kj(self) -> float:
        return self._interval_kj

    def interval_avg_hr(self):
        return self._interval_avg_hr

    def workout_avg_hr(self):
        return self._workout_avg_hr


def _make_tile(
    power_history=None,
    cadence_history=None,
    interval_stats=None,
    now=1.0,
    hr_bpm=None,
) -> TileComputation:
    ph = power_history or _MockPowerHistory()
    ch = cadence_history or _MockCadenceHistory()
    ist = interval_stats or _MockIntervalStats()
    return TileComputation(ph, ch, ist, lambda: now, lambda: hr_bpm)


class TestWindowedAvgPower:
    def test_returns_watts_when_available(self):
        tc = _make_tile(power_history=_MockPowerHistory(windowed=200))
        result = tc.compute("windowed_avg_power", _make_snapshot(), AppSettings())
        assert result == "200 W"

    def test_returns_dash_when_none(self):
        tc = _make_tile(power_history=_MockPowerHistory(windowed=None))
        result = tc.compute("windowed_avg_power", _make_snapshot(), AppSettings())
        assert result == "--"


class TestWindowedAvgFtp:
    def test_returns_percent_when_available(self):
        tc = _make_tile(power_history=_MockPowerHistory(windowed=250))
        settings = AppSettings(ftp=250)
        result = tc.compute("windowed_avg_ftp", _make_snapshot(), settings)
        assert result == "100 %"

    def test_rounds_percent(self):
        tc = _make_tile(power_history=_MockPowerHistory(windowed=125))
        settings = AppSettings(ftp=250)
        result = tc.compute("windowed_avg_ftp", _make_snapshot(), settings)
        assert result == "50 %"

    def test_returns_dash_when_none(self):
        tc = _make_tile(power_history=_MockPowerHistory(windowed=None))
        result = tc.compute("windowed_avg_ftp", _make_snapshot(), AppSettings())
        assert result == "--"


class TestIntervalAvgPower:
    def test_returns_watts_when_available(self):
        ist = _MockIntervalStats(interval_avg=180)
        tc = _make_tile(interval_stats=ist)
        result = tc.compute("interval_avg_power", _make_snapshot(), AppSettings())
        assert result == "180 W"

    def test_returns_dash_when_none(self):
        tc = _make_tile(interval_stats=_MockIntervalStats(interval_avg=None))
        result = tc.compute("interval_avg_power", _make_snapshot(), AppSettings())
        assert result == "--"


class TestWorkoutAvgPower:
    def test_returns_watts_when_available(self):
        tc = _make_tile(power_history=_MockPowerHistory(workout_avg=220))
        result = tc.compute("workout_avg_power", _make_snapshot(), AppSettings())
        assert result == "220 W"

    def test_returns_dash_when_none(self):
        tc = _make_tile(power_history=_MockPowerHistory(workout_avg=None))
        result = tc.compute("workout_avg_power", _make_snapshot(), AppSettings())
        assert result == "--"


class TestWorkoutNormalizedPower:
    def test_returns_watts_when_available(self):
        tc = _make_tile(power_history=_MockPowerHistory(normalized=260))
        result = tc.compute("workout_normalized_power", _make_snapshot(), AppSettings())
        assert result == "260 W"

    def test_returns_dash_when_none(self):
        tc = _make_tile(power_history=_MockPowerHistory(normalized=None))
        result = tc.compute("workout_normalized_power", _make_snapshot(), AppSettings())
        assert result == "--"


class TestHeartRate:
    def test_returns_bpm_when_available(self):
        tc = _make_tile(hr_bpm=145)
        result = tc.compute("heart_rate", _make_snapshot(), AppSettings())
        assert result == "145 bpm"

    def test_returns_dash_when_none(self):
        tc = _make_tile(hr_bpm=None)
        result = tc.compute("heart_rate", _make_snapshot(), AppSettings())
        assert result == "--"


class TestWorkoutAvgHr:
    def test_returns_bpm_when_available(self):
        ist = _MockIntervalStats(workout_avg_hr=155)
        tc = _make_tile(interval_stats=ist)
        result = tc.compute("workout_avg_hr", _make_snapshot(), AppSettings())
        assert result == "155 bpm"

    def test_returns_dash_when_none(self):
        tc = _make_tile(interval_stats=_MockIntervalStats(workout_avg_hr=None))
        result = tc.compute("workout_avg_hr", _make_snapshot(), AppSettings())
        assert result == "--"


class TestIntervalAvgHr:
    def test_returns_bpm_when_available(self):
        ist = _MockIntervalStats(interval_avg_hr=148)
        tc = _make_tile(interval_stats=ist)
        result = tc.compute("interval_avg_hr", _make_snapshot(), AppSettings())
        assert result == "148 bpm"

    def test_returns_dash_when_none(self):
        tc = _make_tile(interval_stats=_MockIntervalStats(interval_avg_hr=None))
        result = tc.compute("interval_avg_hr", _make_snapshot(), AppSettings())
        assert result == "--"


class TestKjWorkCompleted:
    def test_returns_kj_when_workout_avg_exists(self):
        ph = _MockPowerHistory(workout_avg=200, workout_kj=12.345)
        tc = _make_tile(power_history=ph)
        result = tc.compute("kj_work_completed", _make_snapshot(), AppSettings())
        assert result == "12.3 kJ"

    def test_returns_dash_when_no_workout_avg(self):
        tc = _make_tile(power_history=_MockPowerHistory(workout_avg=None))
        result = tc.compute("kj_work_completed", _make_snapshot(), AppSettings())
        assert result == "--"


class TestKjWorkCompletedInterval:
    def test_returns_kj_when_interval_avg_exists(self):
        ist = _MockIntervalStats(interval_avg=150, interval_kj=5.678)
        tc = _make_tile(interval_stats=ist)
        result = tc.compute("kj_work_completed_interval", _make_snapshot(), AppSettings())
        assert result == "5.7 kJ"

    def test_returns_dash_when_no_interval_avg(self):
        tc = _make_tile(interval_stats=_MockIntervalStats(interval_avg=None))
        result = tc.compute("kj_work_completed_interval", _make_snapshot(), AppSettings())
        assert result == "--"


class TestCadenceRpm:
    def test_returns_rpm_when_available(self):
        tc = _make_tile(cadence_history=_MockCadenceHistory(windowed=90))
        result = tc.compute("cadence_rpm", _make_snapshot(), AppSettings())
        assert result == "90 rpm"

    def test_returns_dash_when_none(self):
        tc = _make_tile(cadence_history=_MockCadenceHistory(windowed=None))
        result = tc.compute("cadence_rpm", _make_snapshot(), AppSettings())
        assert result == "--"


class TestUnknownKey:
    def test_unknown_key_returns_dash(self):
        tc = _make_tile()
        result = tc.compute("not_a_real_key", _make_snapshot(), AppSettings())
        assert result == "--"


class TestWindowSettingsRespected:
    def test_windowed_power_uses_settings_window(self):
        """windowed_avg_power passes the configured window to power_history."""
        calls = []

        class TrackingPowerHistory(_MockPowerHistory):
            def windowed_avg(self, now, window_seconds):
                calls.append(window_seconds)
                return 100

        tc = _make_tile(power_history=TrackingPowerHistory())
        settings = AppSettings(windowed_power_window_seconds=7)
        tc.compute("windowed_avg_power", _make_snapshot(), settings)
        assert calls == [7]

    def test_ftp_of_one_prevents_division_by_zero(self):
        """ftp=0 in settings is clamped to 1, avoiding ZeroDivisionError."""
        tc = _make_tile(power_history=_MockPowerHistory(windowed=250))
        settings = AppSettings(ftp=0)
        result = tc.compute("windowed_avg_ftp", _make_snapshot(), settings)
        assert result.endswith(" %")


class TestUpdateScreen:
    def test_update_screen_calls_set_tile_value_for_each_key(self):
        """update_screen iterates tile keys and sets computed values on screen."""

        class MockScreen:
            def __init__(self):
                self.set_calls: dict[str, str] = {}

            def get_selected_tile_keys(self):
                return ["heart_rate", "cadence_rpm"]

            def set_tile_value(self, key, value):
                self.set_calls[key] = value

        screen = MockScreen()
        tc = _make_tile(hr_bpm=130, cadence_history=_MockCadenceHistory(windowed=75))
        tc.update_screen(screen, _make_snapshot(), AppSettings())

        assert screen.set_calls["heart_rate"] == "130 bpm"
        assert screen.set_calls["cadence_rpm"] == "75 rpm"

from __future__ import annotations

import pytest

from opencycletrainer.core.workout_engine import EngineState, WorkoutEngineSnapshot
from opencycletrainer.core.workout_model import Workout, WorkoutInterval
from opencycletrainer.ui.mode_state import DEFAULT_MANUAL_RESISTANCE_OFFSET_PERCENT, ModeState


# ── Helpers ──────────────────────────────────────────────────────────────────


def _snapshot(
    interval_index: int | None = 0,
    interval_elapsed: float = 0.0,
    interval_remaining: float = 300.0,
) -> WorkoutEngineSnapshot:
    return WorkoutEngineSnapshot(
        state=EngineState.RUNNING,
        elapsed_seconds=interval_elapsed,
        riding_elapsed_seconds=interval_elapsed,
        total_duration_seconds=600,
        current_interval_index=interval_index,
        current_interval_elapsed_seconds=interval_elapsed,
        current_interval_remaining_seconds=interval_remaining,
        ramp_in_remaining_seconds=0.0,
        recording_active=True,
        pending_kj_extension=0,
    )


def _simple_workout(
    start_watts: int = 200,
    end_watts: int = 200,
    start_pct: float = 100.0,
    end_pct: float = 100.0,
    duration: int = 300,
    free_ride: bool = False,
) -> Workout:
    return Workout(
        name="Test",
        ftp_watts=200,
        intervals=(
            WorkoutInterval(
                start_offset_seconds=0,
                duration_seconds=duration,
                start_percent_ftp=start_pct,
                end_percent_ftp=end_pct,
                start_target_watts=start_watts,
                end_target_watts=end_watts,
                free_ride=free_ride,
            ),
        ),
    )


def _two_interval_workout(first_free_ride: bool = True) -> Workout:
    """Workout with two intervals: first optionally free-ride, second normal."""
    return Workout(
        name="Two Interval",
        ftp_watts=200,
        intervals=(
            WorkoutInterval(
                start_offset_seconds=0,
                duration_seconds=300,
                start_percent_ftp=0.0,
                end_percent_ftp=0.0,
                start_target_watts=0,
                end_target_watts=0,
                free_ride=first_free_ride,
            ),
            WorkoutInterval(
                start_offset_seconds=300,
                duration_seconds=300,
                start_percent_ftp=85.0,
                end_percent_ftp=85.0,
                start_target_watts=170,
                end_target_watts=170,
            ),
        ),
    )


# ── Defaults ─────────────────────────────────────────────────────────────────


class TestModeStateDefaults:
    def test_initial_selected_mode(self):
        ms = ModeState("ERG")
        assert ms.selected_mode == "ERG"

    def test_initial_selected_mode_resistance(self):
        ms = ModeState("Resistance")
        assert ms.selected_mode == "Resistance"

    def test_is_free_ride_false_by_default(self):
        ms = ModeState("ERG")
        assert ms.is_free_ride is False

    def test_free_ride_erg_target_none_by_default(self):
        ms = ModeState("ERG")
        assert ms.free_ride_erg_target is None

    def test_default_resistance_offset(self):
        ms = ModeState("ERG")
        display_val, show_pct = ms.resistance_display()
        assert display_val == int(DEFAULT_MANUAL_RESISTANCE_OFFSET_PERCENT)
        assert show_pct is True

    def test_custom_initial_resistance_offset(self):
        ms = ModeState("Resistance", initial_resistance_offset_percent=50.0)
        val, _ = ms.resistance_display()
        assert val == 50


# ── active_control_mode ───────────────────────────────────────────────────────


class TestActiveControlMode:
    def test_erg_selected_returns_erg(self):
        ms = ModeState("ERG")
        assert ms.active_control_mode(_snapshot(), _simple_workout()) == "ERG"

    def test_resistance_selected_returns_resistance(self):
        ms = ModeState("Resistance")
        assert ms.active_control_mode(_snapshot(), _simple_workout()) == "Resistance"

    def test_hybrid_below_threshold_returns_erg(self):
        ms = ModeState("Hybrid")
        # 40% FTP is below the 56% recovery threshold
        workout = _simple_workout(start_pct=40.0, end_pct=40.0)
        assert ms.active_control_mode(_snapshot(), workout) == "ERG"

    def test_hybrid_above_threshold_returns_resistance(self):
        ms = ModeState("Hybrid")
        # 80% FTP is above the recovery threshold
        workout = _simple_workout(start_pct=80.0, end_pct=80.0)
        assert ms.active_control_mode(_snapshot(), workout) == "Resistance"

    def test_hybrid_no_workout_returns_erg(self):
        ms = ModeState("Hybrid")
        assert ms.active_control_mode(_snapshot(), None) == "ERG"

    def test_hybrid_no_interval_returns_erg(self):
        ms = ModeState("Hybrid")
        assert ms.active_control_mode(_snapshot(interval_index=None), _simple_workout()) == "ERG"

    def test_free_ride_interval_forces_resistance_regardless_of_erg(self):
        ms = ModeState("ERG")
        workout = _simple_workout(free_ride=True)
        assert ms.active_control_mode(_snapshot(), workout) == "Resistance"

    def test_free_ride_interval_forces_resistance_regardless_of_hybrid(self):
        ms = ModeState("Hybrid")
        workout = _simple_workout(free_ride=True)
        assert ms.active_control_mode(_snapshot(), workout) == "Resistance"

    def test_free_ride_interval_forces_resistance_regardless_of_resistance_mode(self):
        ms = ModeState("Resistance")
        workout = _simple_workout(free_ride=True)
        assert ms.active_control_mode(_snapshot(), workout) == "Resistance"

    def test_normal_interval_after_free_ride_resumes_selected_mode(self):
        ms = ModeState("ERG")
        workout = _two_interval_workout(first_free_ride=True)
        snap = _snapshot(interval_index=1)
        assert ms.active_control_mode(snap, workout) == "ERG"

    def test_out_of_range_interval_index_falls_back_to_selected(self):
        ms = ModeState("ERG")
        workout = _simple_workout()
        snap = _snapshot(interval_index=99)
        assert ms.active_control_mode(snap, workout) == "ERG"

    def test_no_workout_returns_selected_mode(self):
        ms = ModeState("Resistance")
        assert ms.active_control_mode(_snapshot(), None) == "Resistance"


# ── workout_target_watts ──────────────────────────────────────────────────────


class TestWorkoutTargetWatts:
    def test_returns_none_with_no_workout(self):
        ms = ModeState("ERG")
        assert ms.workout_target_watts(_snapshot(), None) is None

    def test_returns_none_with_no_interval_index(self):
        ms = ModeState("ERG")
        assert ms.workout_target_watts(_snapshot(interval_index=None), _simple_workout()) is None

    def test_returns_start_watts_at_interval_start(self):
        ms = ModeState("ERG")
        workout = _simple_workout(start_watts=200, end_watts=200)
        assert ms.workout_target_watts(_snapshot(interval_elapsed=0.0), workout) == 200

    def test_ramp_interpolates_at_midpoint(self):
        ms = ModeState("ERG")
        workout = _simple_workout(start_watts=100, end_watts=200, duration=300)
        snap = _snapshot(interval_elapsed=150.0, interval_remaining=150.0)
        result = ms.workout_target_watts(snap, workout)
        assert result == 150

    def test_returns_end_watts_at_interval_end(self):
        ms = ModeState("ERG")
        workout = _simple_workout(start_watts=100, end_watts=200, duration=300)
        snap = _snapshot(interval_elapsed=300.0, interval_remaining=0.0)
        assert ms.workout_target_watts(snap, workout) == 200


# ── resolve_target_watts ──────────────────────────────────────────────────────


class TestResolveTargetWatts:
    def test_returns_none_with_no_workout(self):
        ms = ModeState("ERG")
        assert ms.resolve_target_watts(_snapshot(), None) is None

    def test_returns_none_in_resistance_mode(self):
        ms = ModeState("Resistance")
        assert ms.resolve_target_watts(_snapshot(), _simple_workout()) is None

    def test_returns_interval_watts_in_erg_mode(self):
        ms = ModeState("ERG")
        workout = _simple_workout(start_watts=200, end_watts=200)
        assert ms.resolve_target_watts(_snapshot(interval_elapsed=0.0), workout) == 200

    def test_jog_offset_applied_to_interval_target(self):
        ms = ModeState("ERG")
        workout = _simple_workout(start_watts=200, end_watts=200)
        ms.jog(10, ftp=200.0, snapshot=_snapshot(), workout=workout)  # +20 W
        result = ms.resolve_target_watts(_snapshot(interval_elapsed=0.0), workout)
        assert result == 220

    def test_negative_jog_cannot_go_below_zero(self):
        ms = ModeState("ERG")
        workout = _simple_workout(start_watts=10, end_watts=10)
        ms.jog(-100, ftp=200.0, snapshot=_snapshot(), workout=workout)  # -200 W
        result = ms.resolve_target_watts(_snapshot(interval_elapsed=0.0), workout)
        assert result == 0

    def test_free_ride_uses_erg_target(self):
        ms = ModeState("ERG")
        ms.set_free_ride(enabled=True, erg_target=None)
        ms.set_erg_target(250)
        workout = _simple_workout()
        assert ms.resolve_target_watts(_snapshot(), workout) == 250

    def test_free_ride_erg_target_plus_jog(self):
        ms = ModeState("ERG")
        ms.set_free_ride(enabled=True, erg_target=None)
        ms.set_erg_target(250)
        workout = _simple_workout()
        ms.jog(10, ftp=200.0, snapshot=_snapshot(), workout=workout)  # +20 W
        result = ms.resolve_target_watts(_snapshot(), workout)
        assert result == 270

    def test_free_ride_with_no_erg_target_returns_none(self):
        ms = ModeState("ERG")
        ms.set_free_ride(enabled=True, erg_target=None)
        workout = _simple_workout()
        assert ms.resolve_target_watts(_snapshot(), workout) is None

    def test_returns_none_for_out_of_range_interval_in_erg(self):
        ms = ModeState("ERG")
        workout = _simple_workout()
        snap = _snapshot(interval_index=99)
        assert ms.resolve_target_watts(snap, workout) is None


# ── resistance_display ────────────────────────────────────────────────────────


class TestResistanceDisplay:
    def test_no_step_count_returns_percent_and_show_true(self):
        ms = ModeState("Resistance", initial_resistance_offset_percent=50.0)
        val, show = ms.resistance_display()
        assert val == 50
        assert show is True

    def test_step_count_100_or_more_returns_percent(self):
        ms = ModeState("Resistance", initial_resistance_offset_percent=50.0)
        ms.set_trainer_resistance_step_count(100)
        val, show = ms.resistance_display()
        assert val == 50
        assert show is True

    def test_step_count_below_100_returns_step_number(self):
        ms = ModeState("Resistance", initial_resistance_offset_percent=50.0)
        ms.set_trainer_resistance_step_count(20)
        val, show = ms.resistance_display()
        # round(20 * 50 / 100) = 10
        assert val == 10
        assert show is False

    def test_step_count_none_resets_to_percent_display(self):
        ms = ModeState("Resistance", initial_resistance_offset_percent=50.0)
        ms.set_trainer_resistance_step_count(20)
        ms.set_trainer_resistance_step_count(None)
        _, show = ms.resistance_display()
        assert show is True


# ── select_mode ───────────────────────────────────────────────────────────────


class TestSelectMode:
    def test_select_mode_updates_selected_mode(self):
        ms = ModeState("ERG")
        ms.select_mode("Resistance")
        assert ms.selected_mode == "Resistance"

    def test_select_hybrid_mode(self):
        ms = ModeState("ERG")
        ms.select_mode("Hybrid")
        assert ms.selected_mode == "Hybrid"


# ── jog ───────────────────────────────────────────────────────────────────────


class TestJog:
    def test_erg_jog_accumulates_watts(self):
        ms = ModeState("ERG")
        workout = _simple_workout()
        ms.jog(10, ftp=200.0, snapshot=_snapshot(), workout=workout)
        assert ms.erg_jog_watts == pytest.approx(20.0)

    def test_erg_jog_accumulates_across_calls(self):
        ms = ModeState("ERG")
        workout = _simple_workout()
        ms.jog(10, ftp=200.0, snapshot=_snapshot(), workout=workout)
        ms.jog(5, ftp=200.0, snapshot=_snapshot(), workout=workout)
        assert ms.erg_jog_watts == pytest.approx(30.0)

    def test_resistance_jog_updates_offset(self):
        ms = ModeState("Resistance", initial_resistance_offset_percent=33.0)
        workout = _simple_workout()
        ms.jog(10, ftp=200.0, snapshot=_snapshot(), workout=workout)
        val, _ = ms.resistance_display()
        assert val == 43

    def test_resistance_jog_clamps_at_100(self):
        ms = ModeState("Resistance", initial_resistance_offset_percent=95.0)
        workout = _simple_workout()
        ms.jog(10, ftp=200.0, snapshot=_snapshot(), workout=workout)
        val, _ = ms.resistance_display()
        assert val == 100

    def test_resistance_jog_clamps_at_negative_100(self):
        ms = ModeState("Resistance", initial_resistance_offset_percent=-95.0)
        workout = _simple_workout()
        ms.jog(-10, ftp=200.0, snapshot=_snapshot(), workout=workout)
        val, _ = ms.resistance_display()
        assert val == -100

    def test_free_ride_interval_jog_updates_resistance(self):
        """Free-ride intervals force Resistance mode, so jog adjusts resistance offset."""
        ms = ModeState("ERG", initial_resistance_offset_percent=33.0)
        workout = _simple_workout(free_ride=True)
        ms.jog(10, ftp=200.0, snapshot=_snapshot(), workout=workout)
        val, _ = ms.resistance_display()
        assert val == 43


# ── reset_jog ─────────────────────────────────────────────────────────────────


class TestResetJog:
    def test_reset_jog_clears_erg_jog_watts(self):
        ms = ModeState("ERG")
        workout = _simple_workout()
        ms.jog(20, ftp=200.0, snapshot=_snapshot(), workout=workout)
        ms.reset_jog()
        assert ms.erg_jog_watts == 0.0

    def test_resolve_target_after_reset_has_no_jog_offset(self):
        ms = ModeState("ERG")
        workout = _simple_workout(start_watts=200, end_watts=200)
        ms.jog(10, ftp=200.0, snapshot=_snapshot(), workout=workout)
        ms.reset_jog()
        assert ms.resolve_target_watts(_snapshot(), workout) == 200


# ── set_free_ride ─────────────────────────────────────────────────────────────


class TestSetFreeRide:
    def test_set_free_ride_true_sets_flag(self):
        ms = ModeState("ERG")
        ms.set_free_ride(enabled=True, erg_target=None)
        assert ms.is_free_ride is True

    def test_set_free_ride_false_clears_flag(self):
        ms = ModeState("ERG")
        ms.set_free_ride(enabled=True, erg_target=None)
        ms.set_free_ride(enabled=False, erg_target=None)
        assert ms.is_free_ride is False

    def test_set_free_ride_stores_erg_target(self):
        ms = ModeState("ERG")
        ms.set_free_ride(enabled=True, erg_target=250)
        assert ms.free_ride_erg_target == 250

    def test_set_free_ride_false_clears_erg_target(self):
        ms = ModeState("ERG")
        ms.set_free_ride(enabled=True, erg_target=250)
        ms.set_free_ride(enabled=False, erg_target=None)
        assert ms.free_ride_erg_target is None


# ── set_erg_target ────────────────────────────────────────────────────────────


class TestSetErgTarget:
    def test_set_erg_target_stores_watts(self):
        ms = ModeState("ERG")
        ms.set_erg_target(300)
        assert ms.free_ride_erg_target == 300

    def test_set_erg_target_switches_to_erg(self):
        ms = ModeState("Resistance")
        ms.set_erg_target(300)
        assert ms.selected_mode == "ERG"

    def test_set_erg_target_resets_jog(self):
        ms = ModeState("ERG")
        workout = _simple_workout()
        ms.jog(20, ftp=200.0, snapshot=_snapshot(), workout=workout)
        ms.set_erg_target(300)
        assert ms.erg_jog_watts == 0.0


# ── set_trainer_resistance_step_count ────────────────────────────────────────


class TestSetTrainerResistanceStepCount:
    def test_set_step_count(self):
        ms = ModeState("Resistance", initial_resistance_offset_percent=50.0)
        ms.set_trainer_resistance_step_count(10)
        val, show = ms.resistance_display()
        assert val == 5  # round(10 * 50 / 100)
        assert show is False

    def test_clear_step_count(self):
        ms = ModeState("Resistance", initial_resistance_offset_percent=50.0)
        ms.set_trainer_resistance_step_count(10)
        ms.set_trainer_resistance_step_count(None)
        _, show = ms.resistance_display()
        assert show is True

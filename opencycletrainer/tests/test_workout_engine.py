from __future__ import annotations

from opencycletrainer.core.workout_engine import EngineState, WorkoutEngine
from opencycletrainer.core.workout_model import Workout, WorkoutInterval


def _build_workout() -> Workout:
    intervals = (
        WorkoutInterval(
            start_offset_seconds=0,
            duration_seconds=10,
            start_percent_ftp=50.0,
            end_percent_ftp=50.0,
            start_target_watts=150,
            end_target_watts=150,
        ),
        WorkoutInterval(
            start_offset_seconds=10,
            duration_seconds=20,
            start_percent_ftp=75.0,
            end_percent_ftp=75.0,
            start_target_watts=225,
            end_target_watts=225,
        ),
        WorkoutInterval(
            start_offset_seconds=30,
            duration_seconds=30,
            start_percent_ftp=90.0,
            end_percent_ftp=90.0,
            start_target_watts=270,
            end_target_watts=270,
        ),
    )
    return Workout(name="Engine Test", ftp_watts=300, intervals=intervals)


def test_engine_interval_progression_matches_schedule():
    engine = WorkoutEngine()
    engine.load_workout(_build_workout())
    engine.start()

    assert engine.tick(0).current_interval_index == 0
    assert engine.tick(5).current_interval_index == 0
    assert engine.tick(10).current_interval_index == 1
    assert engine.tick(29).current_interval_index == 1
    assert engine.tick(30).current_interval_index == 2

    finished = engine.tick(60)
    assert finished.state == EngineState.FINISHED
    assert finished.current_interval_index is None
    assert finished.elapsed_seconds == 60


def test_pause_and_resume_with_ramp_in_countdown():
    engine = WorkoutEngine()
    engine.load_workout(_build_workout())
    engine.start()
    engine.tick(0)
    engine.tick(5)

    paused = engine.pause()
    assert paused.state == EngineState.PAUSED

    engine.tick(20)
    assert engine.snapshot().elapsed_seconds == 5

    ramp_start = engine.resume()
    assert ramp_start.state == EngineState.RAMP_IN
    assert ramp_start.ramp_in_remaining_seconds == 3
    assert ramp_start.recording_active is False

    engine.tick(21)
    ramp_mid = engine.tick(23)
    assert ramp_mid.state == EngineState.RAMP_IN
    assert ramp_mid.ramp_in_remaining_seconds == 1
    assert ramp_mid.elapsed_seconds == 5

    ramp_end = engine.tick(24)
    assert ramp_end.state == EngineState.RUNNING
    assert ramp_end.ramp_in_remaining_seconds == 0
    assert ramp_end.elapsed_seconds == 5

    running = engine.tick(25)
    assert running.state == EngineState.RUNNING
    assert running.recording_active is True
    assert running.elapsed_seconds == 6


def test_pause_during_ramp_in_restarts_pause_resume_logic():
    engine = WorkoutEngine()
    engine.load_workout(_build_workout())
    engine.start()
    engine.tick(0)
    engine.tick(5)
    engine.pause()
    engine.resume()
    engine.tick(6)
    engine.tick(7)

    paused_again = engine.pause()
    assert paused_again.state == EngineState.PAUSED

    resumed_again = engine.resume()
    assert resumed_again.state == EngineState.RAMP_IN
    assert resumed_again.ramp_in_remaining_seconds == 3


def test_skip_interval_jumps_to_current_interval_end():
    engine = WorkoutEngine()
    engine.load_workout(_build_workout())
    engine.start()
    engine.tick(0)
    engine.tick(5)

    skipped_once = engine.skip_interval()
    assert skipped_once.elapsed_seconds == 10
    assert skipped_once.current_interval_index == 1

    engine.tick(15)
    skipped_twice = engine.skip_interval()
    assert skipped_twice.elapsed_seconds == 30
    assert skipped_twice.current_interval_index == 2

    skipped_final = engine.skip_interval()
    assert skipped_final.state == EngineState.FINISHED
    assert skipped_final.elapsed_seconds == 60
    assert skipped_final.current_interval_index is None


def test_extend_interval_updates_duration_for_time_mode():
    engine = WorkoutEngine()
    engine.load_workout(_build_workout())
    engine.start()
    engine.tick(0)
    engine.tick(8)

    extended_short = engine.extend_interval(60)
    assert extended_short.total_duration_seconds == 120
    assert extended_short.current_interval_index == 0

    engine.tick(20)
    assert engine.snapshot().current_interval_index == 0

    extended_long = engine.extend_interval(300)
    assert extended_long.total_duration_seconds == 420
    assert extended_long.current_interval_index == 0


def test_extend_interval_in_kj_mode_is_stubbed_but_recorded():
    engine = WorkoutEngine(kj_mode=True)
    engine.load_workout(_build_workout())
    engine.start()
    engine.tick(0)
    engine.tick(1)

    extended = engine.extend_interval(10)
    assert extended.pending_kj_extension == 10
    assert extended.total_duration_seconds == 60


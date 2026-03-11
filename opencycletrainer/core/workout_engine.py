from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from .workout_model import Workout


class EngineState(str, Enum):
    IDLE = "idle"
    READY = "ready"
    RUNNING = "running"
    PAUSED = "paused"
    RAMP_IN = "ramp_in"
    STOPPED = "stopped"
    FINISHED = "finished"


@dataclass(frozen=True)
class WorkoutEngineSnapshot:
    state: EngineState
    elapsed_seconds: float
    total_duration_seconds: int
    current_interval_index: int | None
    current_interval_elapsed_seconds: float | None
    ramp_in_remaining_seconds: float
    recording_active: bool
    pending_kj_extension: int


class WorkoutEngine:
    def __init__(
        self,
        kj_mode: bool = False,
        ramp_in_duration_seconds: int = 3,
        on_snapshot_update: Callable[[WorkoutEngineSnapshot], None] | None = None,
    ) -> None:
        self.kj_mode = kj_mode
        self.ramp_in_duration_seconds = ramp_in_duration_seconds
        self._on_snapshot_update = on_snapshot_update

        self._workout: Workout | None = None
        self._interval_durations_seconds: list[int] = []
        self._state = EngineState.IDLE
        self._elapsed_seconds = 0.0
        self._last_tick_time: float | None = None
        self._ramp_in_remaining_seconds = 0.0
        self._pending_kj_extension = 0

    @property
    def state(self) -> EngineState:
        return self._state

    @property
    def workout(self) -> Workout | None:
        return self._workout

    @property
    def recording_active(self) -> bool:
        return self._state == EngineState.RUNNING

    def load_workout(self, workout: Workout) -> WorkoutEngineSnapshot:
        if not workout.intervals:
            raise ValueError("Workout must include at least one interval.")

        self._workout = workout
        self._interval_durations_seconds = [interval.duration_seconds for interval in workout.intervals]
        self._elapsed_seconds = 0.0
        self._last_tick_time = None
        self._ramp_in_remaining_seconds = 0.0
        self._pending_kj_extension = 0
        self._state = EngineState.READY
        return self._emit_snapshot()

    def start(self) -> WorkoutEngineSnapshot:
        self._ensure_workout_loaded()
        assert self._workout is not None

        self._interval_durations_seconds = [
            interval.duration_seconds for interval in self._workout.intervals
        ]
        self._elapsed_seconds = 0.0
        self._last_tick_time = None
        self._ramp_in_remaining_seconds = 0.0
        self._pending_kj_extension = 0
        self._state = EngineState.RUNNING
        return self._emit_snapshot()

    def pause(self) -> WorkoutEngineSnapshot:
        if self._state in {EngineState.RUNNING, EngineState.RAMP_IN}:
            self._state = EngineState.PAUSED
            self._ramp_in_remaining_seconds = 0.0
            self._last_tick_time = None
        return self._emit_snapshot()

    def resume(self) -> WorkoutEngineSnapshot:
        if self._state == EngineState.PAUSED:
            self._state = EngineState.RAMP_IN
            self._ramp_in_remaining_seconds = float(self.ramp_in_duration_seconds)
            self._last_tick_time = None
        return self._emit_snapshot()

    def stop(self) -> WorkoutEngineSnapshot:
        if self._workout is None:
            return self._emit_snapshot()

        self._state = EngineState.STOPPED
        self._ramp_in_remaining_seconds = 0.0
        self._last_tick_time = None
        return self._emit_snapshot()

    def tick(self, now: float) -> WorkoutEngineSnapshot:
        now_float = float(now)

        if self._last_tick_time is None:
            self._last_tick_time = now_float
            return self._emit_snapshot()

        delta = now_float - self._last_tick_time
        if delta < 0:
            raise ValueError("tick(now) must be monotonic and non-decreasing.")

        self._last_tick_time = now_float
        if delta == 0:
            return self._emit_snapshot()

        if self._state == EngineState.RUNNING:
            self._advance_elapsed(delta)
        elif self._state == EngineState.RAMP_IN:
            self._advance_ramp(delta)

        return self._emit_snapshot()

    def skip_interval(self) -> WorkoutEngineSnapshot:
        if self._workout is None:
            return self._emit_snapshot()

        current_index = self._current_interval_index()
        if current_index is None:
            return self._emit_snapshot()

        self._elapsed_seconds = float(self._interval_end_offset(current_index))
        self._handle_possible_finish()
        return self._emit_snapshot()

    def extend_interval(self, seconds_or_kj: int) -> WorkoutEngineSnapshot:
        if seconds_or_kj <= 0:
            raise ValueError("Extension value must be greater than zero.")

        if self._workout is None:
            return self._emit_snapshot()

        current_index = self._current_interval_index()
        if current_index is None:
            return self._emit_snapshot()

        if self.kj_mode:
            # kJ mode is not implemented yet, but we retain requested values for future logic.
            self._pending_kj_extension += int(seconds_or_kj)
            return self._emit_snapshot()

        self._interval_durations_seconds[current_index] += int(seconds_or_kj)
        return self._emit_snapshot()

    def snapshot(self) -> WorkoutEngineSnapshot:
        current_index = self._current_interval_index()
        interval_elapsed = None
        if current_index is not None:
            interval_elapsed = self._elapsed_seconds - self._interval_start_offset(current_index)

        return WorkoutEngineSnapshot(
            state=self._state,
            elapsed_seconds=self._elapsed_seconds,
            total_duration_seconds=self._total_duration_seconds(),
            current_interval_index=current_index,
            current_interval_elapsed_seconds=interval_elapsed,
            ramp_in_remaining_seconds=self._ramp_in_remaining_seconds,
            recording_active=self.recording_active,
            pending_kj_extension=self._pending_kj_extension,
        )

    def _emit_snapshot(self) -> WorkoutEngineSnapshot:
        snapshot = self.snapshot()
        if self._on_snapshot_update is not None:
            self._on_snapshot_update(snapshot)
        return snapshot

    def _ensure_workout_loaded(self) -> None:
        if self._workout is None:
            raise RuntimeError("No workout loaded.")

    def _advance_ramp(self, delta: float) -> None:
        if delta < self._ramp_in_remaining_seconds:
            self._ramp_in_remaining_seconds -= delta
            return

        remainder = delta - self._ramp_in_remaining_seconds
        self._ramp_in_remaining_seconds = 0.0
        self._state = EngineState.RUNNING
        if remainder > 0:
            self._advance_elapsed(remainder)

    def _advance_elapsed(self, delta: float) -> None:
        self._elapsed_seconds += delta
        self._handle_possible_finish()

    def _handle_possible_finish(self) -> None:
        total_duration = self._total_duration_seconds()
        if self._elapsed_seconds >= total_duration:
            self._elapsed_seconds = float(total_duration)
            self._state = EngineState.FINISHED
            self._ramp_in_remaining_seconds = 0.0
            self._last_tick_time = None

    def _total_duration_seconds(self) -> int:
        return sum(self._interval_durations_seconds)

    def _interval_start_offset(self, index: int) -> int:
        return sum(self._interval_durations_seconds[:index])

    def _interval_end_offset(self, index: int) -> int:
        return sum(self._interval_durations_seconds[: index + 1])

    def _current_interval_index(self) -> int | None:
        if self._workout is None:
            return None
        if self._elapsed_seconds >= self._total_duration_seconds():
            return None

        elapsed = self._elapsed_seconds
        for index in range(len(self._interval_durations_seconds)):
            if elapsed < self._interval_end_offset(index):
                return index
        return None

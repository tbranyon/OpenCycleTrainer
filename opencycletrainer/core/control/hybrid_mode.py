from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import math
from typing import Protocol

from opencycletrainer.core.control.ftms_control import ControlMode, FTMSControlError
from opencycletrainer.core.workout_engine import EngineState, WorkoutEngineSnapshot
from opencycletrainer.core.workout_model import Workout, WorkoutInterval

RECOVERY_THRESHOLD_PERCENT = 56.0
MIN_RESISTANCE_LEVEL = 0.0
MAX_RESISTANCE_LEVEL = 200.0

HOTKEY_UP = "up"
HOTKEY_DOWN = "down"
HOTKEY_LEFT = "left"
HOTKEY_RIGHT = "right"

HOTKEY_RESISTANCE_DELTAS = {
    HOTKEY_UP: 1.0,
    HOTKEY_DOWN: -1.0,
    HOTKEY_RIGHT: 5.0,
    HOTKEY_LEFT: -5.0,
}


class HybridControl(Protocol):
    @property
    def mode(self) -> ControlMode:
        """Current trainer control mode."""

    def set_mode_erg(self) -> None:
        """Switch to ERG mode."""

    def set_mode_resistance(self) -> None:
        """Switch to resistance mode."""

    def set_erg_target_watts(self, watts: int) -> object:
        """Apply ERG target."""

    def set_resistance_level(self, percent_or_unit: float) -> object:
        """Apply resistance level."""


@dataclass(frozen=True)
class HybridModeStatus:
    active_mode: ControlMode
    in_work_interval: bool
    work_resistance_level: float


class HybridModeController:
    """Hybrid mode orchestration over FTMS control and workout engine snapshots."""

    def __init__(
        self,
        control: HybridControl,
        *,
        recovery_threshold_percent: float = RECOVERY_THRESHOLD_PERCENT,
        alert_callback: Callable[[str], None] | None = None,
        status_callback: Callable[[HybridModeStatus], None] | None = None,
    ) -> None:
        self._control = control
        self._recovery_threshold_percent = float(recovery_threshold_percent)
        self._alert_callback = alert_callback
        self._status_callback = status_callback

        self._work_resistance_level = MIN_RESISTANCE_LEVEL
        self._in_work_interval = False
        self._last_state: EngineState | None = None
        self._last_interval_index: int | None = None

    @property
    def work_resistance_level(self) -> float:
        return self._work_resistance_level

    @property
    def in_work_interval(self) -> bool:
        return self._in_work_interval

    @property
    def active_mode(self) -> ControlMode:
        return self._control.mode

    def on_engine_snapshot(self, snapshot: WorkoutEngineSnapshot, workout: Workout | None) -> None:
        try:
            self._apply_snapshot(snapshot, workout)
        except FTMSControlError as exc:
            self._report_error(f"Trainer control error: {exc}")

    def handle_resistance_hotkey(self, key: str) -> bool:
        delta = HOTKEY_RESISTANCE_DELTAS.get(key.lower().strip())
        if delta is None:
            return False
        return self.jog_resistance(delta)

    def jog_resistance(self, delta_percent: float) -> bool:
        if not self._in_work_interval:
            return False

        current = self._work_resistance_level
        updated = _clamp_resistance(current + float(delta_percent))
        if math.isclose(current, updated, rel_tol=1e-9, abs_tol=1e-9):
            return False

        try:
            self._control.set_mode_resistance()
            self._control.set_resistance_level(updated)
        except FTMSControlError as exc:
            self._report_error(f"Trainer control error: {exc}")
            return False

        self._work_resistance_level = updated
        self._emit_status()
        return True

    def _apply_snapshot(self, snapshot: WorkoutEngineSnapshot, workout: Workout | None) -> None:
        if workout is None:
            self._last_state = snapshot.state
            self._last_interval_index = snapshot.current_interval_index
            return

        inactive_states = {EngineState.PAUSED, EngineState.STOPPED, EngineState.FINISHED}
        if snapshot.state in inactive_states:
            if self._last_state not in inactive_states:
                self._apply_pause_setpoint()
            self._last_state = snapshot.state
            self._last_interval_index = snapshot.current_interval_index
            return

        if snapshot.state != EngineState.RUNNING:
            self._last_state = snapshot.state
            self._last_interval_index = snapshot.current_interval_index
            return

        interval_changed = snapshot.current_interval_index != self._last_interval_index
        entered_running = self._last_state != EngineState.RUNNING
        if interval_changed or entered_running:
            self._apply_interval_setpoint(snapshot, workout)

        self._last_state = snapshot.state
        self._last_interval_index = snapshot.current_interval_index

    def _apply_pause_setpoint(self) -> None:
        if self._control.mode is ControlMode.ERG:
            self._control.set_erg_target_watts(0)
        else:
            self._control.set_resistance_level(0)

    def _apply_interval_setpoint(self, snapshot: WorkoutEngineSnapshot, workout: Workout) -> None:
        interval_index = snapshot.current_interval_index
        if interval_index is None:
            return

        interval = workout.intervals[interval_index]
        is_work = _is_work_interval(interval, self._recovery_threshold_percent)

        if is_work:
            self._apply_work_interval(interval)
        else:
            self._apply_recovery_interval(interval, snapshot.current_interval_elapsed_seconds or 0.0)

        self._emit_status()

    def _apply_work_interval(self, interval: WorkoutInterval) -> None:
        if self._work_resistance_level <= MIN_RESISTANCE_LEVEL:
            self._work_resistance_level = _default_work_resistance(interval)
        self._control.set_mode_resistance()
        self._control.set_resistance_level(self._work_resistance_level)
        self._in_work_interval = True

    def _apply_recovery_interval(self, interval: WorkoutInterval, elapsed_in_interval: float) -> None:
        target_watts = _resolve_interval_target_watts(interval, elapsed_in_interval)
        self._control.set_mode_erg()
        self._control.set_erg_target_watts(target_watts)
        self._in_work_interval = False

    def _emit_status(self) -> None:
        if self._status_callback is None:
            return
        self._status_callback(
            HybridModeStatus(
                active_mode=self._control.mode,
                in_work_interval=self._in_work_interval,
                work_resistance_level=self._work_resistance_level,
            ),
        )

    def _report_error(self, message: str) -> None:
        if self._alert_callback is not None:
            self._alert_callback(message)


def _is_work_interval(interval: WorkoutInterval, recovery_threshold_percent: float) -> bool:
    return interval.start_percent_ftp >= recovery_threshold_percent


def _default_work_resistance(interval: WorkoutInterval) -> float:
    return _clamp_resistance(interval.start_percent_ftp)


def _resolve_interval_target_watts(interval: WorkoutInterval, elapsed_in_interval: float) -> int:
    target = _interpolate_interval(
        start_value=float(interval.start_target_watts),
        end_value=float(interval.end_target_watts),
        duration_seconds=interval.duration_seconds,
        elapsed_seconds=elapsed_in_interval,
    )
    return int(round(target))


def _interpolate_interval(
    *,
    start_value: float,
    end_value: float,
    duration_seconds: int,
    elapsed_seconds: float,
) -> float:
    if duration_seconds <= 0:
        return end_value
    elapsed_clamped = min(max(float(elapsed_seconds), 0.0), float(duration_seconds))
    ratio = elapsed_clamped / float(duration_seconds)
    return start_value + (end_value - start_value) * ratio


def _clamp_resistance(value: float) -> float:
    clamped = min(max(float(value), MIN_RESISTANCE_LEVEL), MAX_RESISTANCE_LEVEL)
    return round(clamped, 1)

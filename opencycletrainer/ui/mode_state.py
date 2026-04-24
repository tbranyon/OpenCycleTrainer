from __future__ import annotations

from opencycletrainer.core.workout_engine import WorkoutEngineSnapshot
from opencycletrainer.core.workout_model import Workout

RECOVERY_THRESHOLD_PERCENT = 56.0
DEFAULT_MANUAL_RESISTANCE_OFFSET_PERCENT = 33.0
DEFAULT_FREE_RIDE_ERG_TARGET_WATTS = 100


class ModeState:
    """Owns mode selection, ERG jog offset, and resistance offset state."""

    def __init__(
        self,
        initial_selected_mode: str,
        initial_resistance_offset_percent: float = DEFAULT_MANUAL_RESISTANCE_OFFSET_PERCENT,
    ) -> None:
        self._selected_mode = initial_selected_mode
        self._manual_resistance_offset_percent = initial_resistance_offset_percent
        self._manual_erg_jog_watts = 0.0
        self._is_free_ride = False
        self._free_ride_erg_target_watts: int | None = None
        self._trainer_resistance_step_count: int | None = None

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def selected_mode(self) -> str:
        return self._selected_mode

    @property
    def is_free_ride(self) -> bool:
        return self._is_free_ride

    @property
    def free_ride_erg_target(self) -> int | None:
        return self._free_ride_erg_target_watts

    @property
    def erg_jog_watts(self) -> float:
        """Current ERG jog offset in watts, for use in FTMS bridge dispatch."""
        return self._manual_erg_jog_watts

    # ── Mode logic ────────────────────────────────────────────────────────────

    def active_control_mode(
        self, snapshot: WorkoutEngineSnapshot, workout: Workout | None
    ) -> str:
        """Return the effective control mode given current state and workout position."""
        if workout is not None:
            index = snapshot.current_interval_index
            if index is not None and 0 <= index < len(workout.intervals):
                if workout.intervals[index].free_ride:
                    return "Resistance"

        if self._selected_mode == "ERG":
            return "ERG"
        if self._selected_mode == "Resistance":
            return "Resistance"
        # Hybrid: use workout interval intensity to decide
        if workout is None:
            return "ERG"
        index = snapshot.current_interval_index
        if index is None or index < 0 or index >= len(workout.intervals):
            return "ERG"
        interval = workout.intervals[index]
        if interval.start_percent_ftp < RECOVERY_THRESHOLD_PERCENT:
            return "ERG"
        return "Resistance"

    def workout_target_watts(
        self, snapshot: WorkoutEngineSnapshot, workout: Workout | None
    ) -> int | None:
        """Return raw workout target power regardless of control mode."""
        if workout is None:
            return None
        index = snapshot.current_interval_index
        if index is None or index < 0 or index >= len(workout.intervals):
            return None
        interval = workout.intervals[index]
        elapsed = float(snapshot.current_interval_elapsed_seconds or 0.0)
        duration = max(float(interval.duration_seconds), 1.0)
        ratio = min(max(elapsed, 0.0), duration) / duration
        target = float(interval.start_target_watts) + (
            float(interval.end_target_watts) - float(interval.start_target_watts)
        ) * ratio
        return int(round(target))

    def resolve_target_watts(
        self, snapshot: WorkoutEngineSnapshot, workout: Workout | None
    ) -> int | None:
        """Return the ERG setpoint to command, or None if not in ERG mode."""
        if workout is None:
            return None
        if self.active_control_mode(snapshot, workout) != "ERG":
            return None

        if self._is_free_ride:
            if self._free_ride_erg_target_watts is None:
                return None
            return int(round(max(0, self._free_ride_erg_target_watts + self._manual_erg_jog_watts)))

        index = snapshot.current_interval_index
        if index is None or index < 0 or index >= len(workout.intervals):
            return None
        interval = workout.intervals[index]
        elapsed = float(snapshot.current_interval_elapsed_seconds or 0.0)
        duration = max(float(interval.duration_seconds), 1.0)
        ratio = min(max(elapsed, 0.0), duration) / duration
        target = float(interval.start_target_watts) + (
            float(interval.end_target_watts) - float(interval.start_target_watts)
        ) * ratio
        return int(round(max(0, target + self._manual_erg_jog_watts)))

    def resistance_display(self) -> tuple[int, bool]:
        """Return (display_value, show_percent) for the resistance level UI.

        When the trainer has fewer than 100 discrete steps, returns the raw step
        number (no percent sign) so each UI step maps to a real trainer step.
        """
        percent = self._manual_resistance_offset_percent
        step_count = self._trainer_resistance_step_count
        if step_count is not None and step_count < 100:
            return round(step_count * percent / 100), False
        return int(percent), True

    def resistance_target_percent(self) -> float:
        """Return the FTMS-safe resistance target percentage for manual mode."""
        return max(0.0, min(100.0, self._manual_resistance_offset_percent))

    # ── Mutations ─────────────────────────────────────────────────────────────

    def select_mode(self, mode: str) -> None:
        """Update the user-selected control mode."""
        self._selected_mode = mode

    def jog(
        self,
        delta_percent: int,
        ftp: float,
        snapshot: WorkoutEngineSnapshot,
        workout: Workout | None,
    ) -> None:
        """Adjust the jog offset for the active control mode."""
        active_mode = self.active_control_mode(snapshot, workout)
        if active_mode == "ERG":
            self._manual_erg_jog_watts += (ftp * delta_percent) / 100.0
        elif active_mode == "Resistance":
            updated = self._manual_resistance_offset_percent + float(delta_percent)
            self._manual_resistance_offset_percent = max(-100.0, min(100.0, updated))

    def reset_jog(self) -> None:
        """Reset the ERG jog offset to zero (called on interval boundary)."""
        self._manual_erg_jog_watts = 0.0

    def set_free_ride(self, enabled: bool, erg_target: int | None) -> None:
        """Enable or disable free-ride mode and set an optional ERG target."""
        self._is_free_ride = enabled
        self._free_ride_erg_target_watts = erg_target

    def set_erg_target(self, watts: int) -> None:
        """Set a free-ride ERG target, switch to ERG mode, and reset jog."""
        self._free_ride_erg_target_watts = watts
        self._selected_mode = "ERG"
        self._manual_erg_jog_watts = 0.0

    def set_trainer_resistance_step_count(self, n: int | None) -> None:
        """Update the number of discrete resistance steps reported by the trainer."""
        self._trainer_resistance_step_count = n

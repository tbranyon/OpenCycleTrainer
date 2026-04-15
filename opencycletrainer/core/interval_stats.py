from __future__ import annotations


class IntervalStats:
    """Per-interval and workout-level HR/power accumulator."""

    def __init__(self) -> None:
        self._interval_power_sum = 0.0
        self._interval_power_count = 0
        self._interval_actual_kj = 0.0
        self._last_actual_power_tick: float | None = None
        self._interval_hr_sum = 0.0
        self._interval_hr_count = 0
        self._workout_hr_sum = 0.0
        self._workout_hr_count = 0

    def record_power(self, watts: int, now: float, recording_active: bool) -> None:
        """Record a power sample and update interval-level accumulators."""
        self._interval_power_sum += float(watts)
        self._interval_power_count += 1
        if self._last_actual_power_tick is not None:
            delta = now - self._last_actual_power_tick
            if delta > 0 and recording_active:
                self._interval_actual_kj += float(watts) * delta / 1000.0
        self._last_actual_power_tick = now

    def record_hr(self, bpm: int) -> None:
        """Record a heart rate sample at both interval and workout scope."""
        self._interval_hr_sum += float(bpm)
        self._interval_hr_count += 1
        self._workout_hr_sum += float(bpm)
        self._workout_hr_count += 1

    def reset_interval(self) -> None:
        """Clear interval-scoped accumulators; workout HR is preserved."""
        self._interval_power_sum = 0.0
        self._interval_power_count = 0
        self._interval_actual_kj = 0.0
        self._last_actual_power_tick = None
        self._interval_hr_sum = 0.0
        self._interval_hr_count = 0

    def reset_workout(self) -> None:
        """Clear all accumulators for a new workout."""
        self._interval_power_sum = 0.0
        self._interval_power_count = 0
        self._interval_actual_kj = 0.0
        self._last_actual_power_tick = None
        self._interval_hr_sum = 0.0
        self._interval_hr_count = 0
        self._workout_hr_sum = 0.0
        self._workout_hr_count = 0

    def interval_avg_watts(self) -> int | None:
        """Return mean watts for the current interval, or None if no samples."""
        if not self._interval_power_count:
            return None
        return round(self._interval_power_sum / self._interval_power_count)

    def interval_actual_kj(self) -> float:
        """Return measured energy (kJ) accumulated during the current interval while recording."""
        return self._interval_actual_kj

    def interval_avg_hr(self) -> int | None:
        """Return mean heart rate for the current interval, or None if no samples."""
        if not self._interval_hr_count:
            return None
        return round(self._interval_hr_sum / self._interval_hr_count)

    def workout_avg_hr(self) -> int | None:
        """Return mean heart rate for the entire workout, or None if no samples."""
        if not self._workout_hr_count:
            return None
        return round(self._workout_hr_sum / self._workout_hr_count)

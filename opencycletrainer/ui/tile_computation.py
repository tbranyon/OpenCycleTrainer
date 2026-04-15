from __future__ import annotations

from collections.abc import Callable


class TileComputation:
    """Stateless tile value computation; holds read-only references to sub-objects."""

    def __init__(
        self,
        power_history,
        cadence_history,
        interval_stats,
        monotonic_clock: Callable[[], float],
        hr_source: Callable[[], int | None],
    ) -> None:
        self._power_history = power_history
        self._cadence_history = cadence_history
        self._interval_stats = interval_stats
        self._monotonic_clock = monotonic_clock
        self._hr_source = hr_source

    def compute(self, key: str, snapshot, settings) -> str:  # noqa: ARG002
        """Return the formatted display string for a single tile key."""
        ftp = max(1, int(settings.ftp))
        window = max(1, int(settings.windowed_power_window_seconds))
        now = self._monotonic_clock()

        if key == "windowed_avg_power":
            val = self._power_history.windowed_avg(now, window)
            return f"{val} W" if val is not None else "--"
        if key == "windowed_avg_ftp":
            val = self._power_history.windowed_avg(now, window)
            return f"{round(val / ftp * 100)} %" if val is not None else "--"
        if key == "interval_avg_power":
            val = self._interval_stats.interval_avg_watts()
            return f"{val} W" if val is not None else "--"
        if key == "workout_avg_power":
            val = self._power_history.workout_avg_watts()
            return f"{val} W" if val is not None else "--"
        if key == "workout_normalized_power":
            val = self._power_history.compute_normalized_power()
            return f"{val} W" if val is not None else "--"
        if key == "heart_rate":
            val = self._hr_source()
            return f"{val} bpm" if val is not None else "--"
        if key == "workout_avg_hr":
            val = self._interval_stats.workout_avg_hr()
            return f"{val} bpm" if val is not None else "--"
        if key == "interval_avg_hr":
            val = self._interval_stats.interval_avg_hr()
            return f"{val} bpm" if val is not None else "--"
        if key == "kj_work_completed":
            if self._power_history.workout_avg_watts() is None:
                return "--"
            return f"{self._power_history.workout_actual_kj():.1f} kJ"
        if key == "kj_work_completed_interval":
            if self._interval_stats.interval_avg_watts() is None:
                return "--"
            return f"{self._interval_stats.interval_actual_kj():.1f} kJ"
        if key == "cadence_rpm":
            val = self._cadence_history.windowed_avg(now)
            return f"{val} rpm" if val is not None else "--"
        return "--"

    def update_screen(self, screen, snapshot, settings) -> None:
        """Recompute all selected tile values and push them to the screen."""
        for key in screen.get_selected_tile_keys():
            screen.set_tile_value(key, self.compute(key, snapshot, settings))

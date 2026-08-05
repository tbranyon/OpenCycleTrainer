from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from opencycletrainer.core.power_history import PowerHistory
    from opencycletrainer.ui.pause_state import PauseState

CHART_UPDATE_INTERVAL_MS = 1000


class ChartHistory:
    """Owns the chart-update timer, HR history, and skip-event list.

    Computes the elapsed-time cursor position and pushes updated power/HR series
    to the screen on each timer tick.
    """

    def __init__(
        self,
        screen: Any,
        monotonic_clock: Callable[[], float],
        power_history: PowerHistory,
        pause_state: PauseState,
        *,
        _timer_factory: Callable[[], Any] | None = None,
    ) -> None:
        self._screen = screen
        self._monotonic_clock = monotonic_clock
        self._power_history = power_history
        self._pause_state = pause_state

        self._chart_start_monotonic: float | None = None
        self._hr_history: list[tuple[float, int]] = []
        self._alpha1_history: list[tuple[float, float]] = []
        self._skip_events: list[tuple[float, float, float]] = []
        self._pause_events: list[tuple[float, float]] = []  # (end_mono, duration)

        if _timer_factory is not None:
            self._chart_timer = _timer_factory()
        else:
            from PySide6.QtCore import QTimer
            self._chart_timer = QTimer()
        self._chart_timer.setInterval(CHART_UPDATE_INTERVAL_MS)

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def chart_timer(self) -> Any:
        return self._chart_timer

    @property
    def chart_start_monotonic(self) -> float | None:
        return self._chart_start_monotonic

    @property
    def hr_history(self) -> list[tuple[float, int]]:
        return self._hr_history

    @property
    def alpha1_series(self) -> list[tuple[float, float]]:
        """α1 samples as (elapsed_seconds, value), skip/pause-adjusted like the other traces."""
        return [
            (self._adjusted_time(mono), value)
            for mono, value in self._alpha1_history
        ]

    @property
    def skip_events(self) -> list[tuple[float, float, float]]:
        return self._skip_events

    # ── Interface ─────────────────────────────────────────────────────────────

    def start(self, now: float) -> None:
        """Set the chart start time and start the update timer."""
        self._chart_start_monotonic = now
        self._chart_timer.start()

    def stop(self) -> None:
        """Stop the chart update timer."""
        self._chart_timer.stop()

    def reset(self) -> None:
        """Clear all chart data (call before each workout or free-ride start)."""
        self._chart_start_monotonic = None
        self._hr_history = []
        self._alpha1_history = []
        self._skip_events = []
        self._pause_events = []

    def record_hr(self, bpm: int, now: float) -> None:
        """Append an HR sample. No-op if the chart has not been started."""
        if self._chart_start_monotonic is None:
            return
        self._hr_history.append((now, int(bpm)))

    def record_dfa_alpha1(self, alpha1: float | None, now: float) -> None:
        """Append a DFA α1 sample, keyed by monotonic time like the HR history.

        No-op if the chart has not been started. ``None`` (a suppressed
        POOR/INSUFFICIENT window) is stored as NaN so the chart overlay renders
        a gap instead of a point.
        """
        if self._chart_start_monotonic is None:
            return
        value = float("nan") if alpha1 is None else float(alpha1)
        self._alpha1_history.append((float(now), value))

    def record_skip(self, now: float, elapsed_before: float, elapsed_after: float) -> None:
        """Record a skip event so the elapsed cursor can account for skipped time."""
        self._skip_events.append((now, elapsed_before, elapsed_after))

    def record_pause(self, end_mono: float, duration: float) -> None:
        """Record a completed pause (including ramp-in) so data timestamps are adjusted."""
        self._pause_events.append((end_mono, duration))

    def _adjusted_time(self, sample_mono: float) -> float:
        """Convert a monotonic sample time to chart-elapsed time.

        Samples taken after a skip are shifted forward by the cumulative skipped
        duration, and paused time is subtracted, so every trace lands at the
        correct position on the workout timeline.
        """
        if self._chart_start_monotonic is None:
            return 0.0
        skip_offset = sum(
            after - before
            for skip_mono, before, after in self._skip_events
            if skip_mono <= sample_mono
        )
        pause_offset = sum(
            dur
            for end_mono, dur in self._pause_events
            if end_mono <= sample_mono
        )
        return (sample_mono - self._chart_start_monotonic) + skip_offset - pause_offset

    def on_tick(self, snapshot: Any, workout: Any, is_free_ride: bool, erg_target_watts: int | None = None) -> None:
        """Recompute elapsed time and push updated series to the screen."""
        if self._chart_start_monotonic is None:
            return

        now = self._monotonic_clock()
        skip_offset = sum(after - before for _, before, after in self._skip_events)
        paused = self._pause_state.total_paused_plus_current(now)
        elapsed = (now - self._chart_start_monotonic) + skip_offset - paused

        power_series = [
            (self._adjusted_time(mono), watts)
            for mono, watts in self._power_history.smoothed_series()
        ]

        hr_series = [
            (self._adjusted_time(mono), bpm)
            for mono, bpm in self._hr_history
        ]

        interval_index = (
            snapshot.current_interval_index if snapshot is not None else None
        )

        alpha1_series = self.alpha1_series

        if is_free_ride:
            self._screen.update_free_ride_charts(
                elapsed, power_series, hr_series, erg_target_watts, alpha1_series
            )
        else:
            self._screen.update_charts(
                elapsed, interval_index, power_series, hr_series, alpha1_series
            )

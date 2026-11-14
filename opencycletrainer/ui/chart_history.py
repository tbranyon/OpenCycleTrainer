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
    to the screen on each timer tick. Chart-time series are cached and extended with
    only the samples that arrived since the previous tick, so per-tick cost does not
    grow with ride length; the cache is rebuilt when a skip or pause shifts the timeline.
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

        self._power_points: list[tuple[float, int]] = []
        self._hr_points: list[tuple[float, int]] = []
        self._alpha1_points: list[tuple[float, float]] = []
        self._points_timeline_key: tuple[float, int, int] | None = None

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
        self._sync_points()
        return list(self._alpha1_points)

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
        self._clear_points()

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

    def _clear_points(self) -> None:
        self._power_points = []
        self._hr_points = []
        self._alpha1_points = []
        self._points_timeline_key = None

    def _sync_points(self) -> None:
        """Bring the cached chart-time series up to date with the raw histories.

        Already-converted points keep their positions unless the timeline itself
        changed (a new start time, skip or pause), in which case every point is
        converted again.
        """
        if self._chart_start_monotonic is None:
            return
        timeline_key = (
            self._chart_start_monotonic,
            len(self._skip_events),
            len(self._pause_events),
        )
        if timeline_key != self._points_timeline_key:
            self._clear_points()
            self._points_timeline_key = timeline_key

        new_power = self._power_history.smoothed_series(start_index=len(self._power_points))
        self._power_points.extend((self._adjusted_time(mono), watts) for mono, watts in new_power)
        self._hr_points.extend(
            (self._adjusted_time(mono), bpm)
            for mono, bpm in self._hr_history[len(self._hr_points):]
        )
        self._alpha1_points.extend(
            (self._adjusted_time(mono), value)
            for mono, value in self._alpha1_history[len(self._alpha1_points):]
        )

    def on_tick(self, snapshot: Any, workout: Any, is_free_ride: bool, erg_target_watts: int | None = None) -> None:
        """Recompute elapsed time and push updated series to the screen."""
        if self._chart_start_monotonic is None:
            return

        now = self._monotonic_clock()
        skip_offset = sum(after - before for _, before, after in self._skip_events)
        paused = self._pause_state.total_paused_plus_current(now)
        elapsed = (now - self._chart_start_monotonic) + skip_offset - paused

        self._sync_points()
        power_series = list(self._power_points)
        hr_series = list(self._hr_points)
        alpha1_series = list(self._alpha1_points)

        interval_index = (
            snapshot.current_interval_index if snapshot is not None else None
        )

        if is_free_ride:
            self._screen.update_free_ride_charts(
                elapsed, power_series, hr_series, erg_target_watts, alpha1_series
            )
        else:
            self._screen.update_charts(
                elapsed, interval_index, power_series, hr_series, alpha1_series
            )

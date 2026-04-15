from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .workout_screen import PauseDialog, WorkoutScreen


class PauseState:
    """Owns PauseDialog lifecycle and elapsed-time bookkeeping for paused duration."""

    def __init__(
        self,
        screen: WorkoutScreen,
        resume_callback: Callable[[], None],
        *,
        _dialog_factory: Callable[[Any], PauseDialog] | None = None,
    ) -> None:
        self._screen = screen
        self._resume_callback = resume_callback
        self._dialog_factory = _dialog_factory
        self._pause_dialog: PauseDialog | None = None
        self._pause_start_monotonic: float | None = None
        self._total_paused_duration: float = 0.0

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def pause_dialog(self) -> PauseDialog | None:
        return self._pause_dialog

    @property
    def pause_start_monotonic(self) -> float | None:
        return self._pause_start_monotonic

    @property
    def total_paused_duration(self) -> float:
        return self._total_paused_duration

    # ── Interface ─────────────────────────────────────────────────────────────

    def pause(self, now: float) -> None:
        """Record pause start time, create and show the pause dialog."""
        self._pause_start_monotonic = now
        factory = self._dialog_factory
        if factory is None:
            from .workout_screen import PauseDialog
            factory = PauseDialog
        self._pause_dialog = factory(self._screen)
        self._pause_dialog.resume_started.connect(self._resume_callback)
        self._pause_dialog.show()

    def resume(self) -> None:
        """Called when resume is initiated.

        Pause duration is not cleared here; it is accumulated when the
        RAMP_IN → RUNNING transition is detected via on_ramp_in_to_running().
        """

    def on_ramp_in_to_running(self, now: float) -> None:
        """Accumulate paused duration on RAMP_IN → RUNNING transition."""
        if self._pause_start_monotonic is not None:
            self._total_paused_duration += now - self._pause_start_monotonic
            self._pause_start_monotonic = None

    def total_paused_plus_current(self, now: float) -> float:
        """Return total paused seconds including the current active pause."""
        paused = self._total_paused_duration
        if self._pause_start_monotonic is not None:
            paused += now - self._pause_start_monotonic
        return paused

    def close_dialog(self) -> None:
        """Close and release the pause dialog."""
        if self._pause_dialog is not None:
            self._pause_dialog.close()
            self._pause_dialog = None

    def reset(self) -> None:
        """Reset all pause state (called at workout start)."""
        self._pause_start_monotonic = None
        self._total_paused_duration = 0.0

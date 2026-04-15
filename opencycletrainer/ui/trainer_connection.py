"""TrainerConnection — owns trainer backend/device-ID state and connection-change alerts."""
from __future__ import annotations

from collections.abc import Callable


class TrainerConnection:
    """Tracks the active trainer backend and device ID, and emits alerts on connection changes."""

    def __init__(
        self,
        screen: object,
        is_workout_active: Callable[[], bool],
    ) -> None:
        self._screen = screen
        self._is_workout_active = is_workout_active

        self._trainer_backend: object | None = None
        self._trainer_device_id: str | None = None
        self._last_known_trainer_id: str | None = None

    @property
    def backend(self) -> object | None:
        """The current trainer backend object."""
        return self._trainer_backend

    @property
    def device_id(self) -> str | None:
        """The current trainer device ID, or None when disconnected."""
        return self._trainer_device_id

    @property
    def last_known_id(self) -> str | None:
        """The most recent non-None trainer device ID seen."""
        return self._last_known_trainer_id

    def set_target(self, backend: object, trainer_device_id: str | None) -> None:
        """Update the trainer target and emit connection-change alerts when a workout is active."""
        old_id = self._trainer_device_id
        self._trainer_backend = backend
        self._trainer_device_id = trainer_device_id
        self._notify_connection_change(old_id, trainer_device_id)

    def _notify_connection_change(self, old_id: str | None, new_id: str | None) -> None:
        """Show a subtle alert when the trainer connects or disconnects during an active workout."""
        if not self._is_workout_active():
            if new_id is not None:
                self._last_known_trainer_id = new_id
            return
        if old_id is not None and new_id is None:
            self._screen.show_alert("Trainer disconnected. Reconnecting...", "info")
        elif old_id is None and new_id is not None and self._last_known_trainer_id is not None:
            self._screen.show_alert("Trainer reconnected", "success")
        if new_id is not None:
            self._last_known_trainer_id = new_id

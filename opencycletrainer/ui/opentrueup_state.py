from __future__ import annotations

from collections.abc import Callable

from opencycletrainer.core.control.opentrueup import OpenTrueUpController
from opencycletrainer.storage.opentrueup_offsets import OpenTrueUpOffsetStore
from opencycletrainer.storage.settings import AppSettings


class OpenTrueUpState:
    """Thin wrapper managing the optional OpenTrueUp bias-correction controller."""

    def __init__(
        self,
        opentrueup: OpenTrueUpController | None,
        offset_callback: Callable[[int | None], None],
    ) -> None:
        self._opentrueup = opentrueup
        self._offset_callback = offset_callback

    @property
    def controller(self) -> OpenTrueUpController | None:
        """The underlying OpenTrueUpController, or None if disabled."""
        return self._opentrueup

    @property
    def enabled(self) -> bool:
        """True if an OpenTrueUp controller is active."""
        return self._opentrueup is not None

    def feed(
        self,
        timestamp: float,
        trainer_watts: int | None,
        bike_watts: int | None,
    ) -> None:
        """Feed a trainer/bike power sample pair; emits offset callback if updated."""
        if self._opentrueup is None:
            return
        try:
            status = self._opentrueup.record_power_sample(
                timestamp=timestamp,
                trainer_power_watts=trainer_watts,
                bike_power_watts=bike_watts,
            )
        except ValueError:
            return
        self._offset_callback(status.last_computed_offset_watts)

    def handle_bridge_status(self, status: object) -> None:
        """Relay an OpenTrueUp status update from the FTMS bridge to the UI."""
        offset = getattr(status, "last_computed_offset_watts", None)
        self._offset_callback(offset)

    @classmethod
    def from_settings(
        cls,
        settings: AppSettings,
        offset_callback: Callable[[int | None], None],
    ) -> OpenTrueUpState:
        """Construct an OpenTrueUpState using the current AppSettings."""
        return cls(_make_opentrueup(settings), offset_callback)

    def enable(self, settings: AppSettings) -> None:
        """Create a fresh OpenTrueUpController from settings if not already enabled."""
        if self._opentrueup is not None:
            return
        self._opentrueup = _make_opentrueup(settings)

    def disable(self) -> None:
        """Destroy the controller and clear the UI offset display."""
        self._opentrueup = None
        self._offset_callback(None)


def _make_opentrueup(settings: AppSettings) -> OpenTrueUpController | None:
    """Construct an OpenTrueUpController if enabled in settings."""
    if not settings.opentrueup_enabled:
        return None
    return OpenTrueUpController(
        enabled=True,
        offset_store=OpenTrueUpOffsetStore(),
    )

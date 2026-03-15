"""App-level singletons: device manager, workout library, and trainer-changed callbacks.

Initialised lazily on first access.  Because OpenCycleTrainer runs as a single-user
native desktop app (one Python process, one webview), module-level singletons are safe.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

_logger = logging.getLogger(__name__)

# ── Private state ──────────────────────────────────────────────────────────

_device_manager = None
_library = None
_trainer_changed_callbacks: list[Callable] = []


# ── Device manager ─────────────────────────────────────────────────────────


def get_device_manager():
    """Return the singleton DeviceManager, initialising it on first call.

    Attempts BleakDeviceBackend; falls back to MockDeviceBackend.
    """
    global _device_manager
    if _device_manager is None:
        _device_manager = _create_device_manager()
    return _device_manager


def set_device_manager(manager) -> None:
    """Replace the singleton with *manager* (used when switching backends in UI)."""
    global _device_manager
    _device_manager = manager


def _create_device_manager():
    try:
        from opencycletrainer.devices.ble_backend import BleakDeviceBackend  # noqa: PLC0415
        from opencycletrainer.storage.paired_devices import PairedDeviceStore  # noqa: PLC0415

        return BleakDeviceBackend(paired_device_store=PairedDeviceStore())
    except Exception as exc:
        _logger.warning("BleakDeviceBackend unavailable, using Mock: %s", exc)
        from opencycletrainer.devices.mock_backend import MockDeviceBackend  # noqa: PLC0415

        return MockDeviceBackend()


# ── Workout library ────────────────────────────────────────────────────────


def get_library():
    """Return the singleton WorkoutLibrary, initialising it on first call."""
    global _library
    if _library is None:
        from opencycletrainer.core.workout_library import WorkoutLibrary  # noqa: PLC0415

        _library = WorkoutLibrary()
    return _library


# ── Trainer device changed notifications ─────────────────────────────────


def register_trainer_changed_callback(cb: Callable) -> None:
    """Register a callback invoked when the connected trainer device changes.

    Signature: ``cb(backend: DeviceManager, trainer_device_id: str | None)``.
    """
    if cb not in _trainer_changed_callbacks:
        _trainer_changed_callbacks.append(cb)


def unregister_trainer_changed_callback(cb: Callable) -> None:
    """Remove a previously registered callback."""
    try:
        _trainer_changed_callbacks.remove(cb)
    except ValueError:
        pass


def notify_trainer_changed(backend, trainer_device_id: str | None) -> None:
    """Invoke all registered trainer-changed callbacks."""
    for cb in list(_trainer_changed_callbacks):
        try:
            cb(backend, trainer_device_id)
        except Exception:
            _logger.exception("Trainer-changed callback raised")


# ── Strava upload function ─────────────────────────────────────────────────


def get_strava_upload_fn() -> Callable[[Path, Path | None], None] | None:
    """Return the Strava upload function if tokens are available, else None."""
    try:
        from opencycletrainer.integrations.strava.token_store import get_tokens  # noqa: PLC0415
        from opencycletrainer.integrations.strava.sync_service import upload_fit_to_strava  # noqa: PLC0415

        if get_tokens() is not None:
            return upload_fit_to_strava
    except Exception:
        pass
    return None

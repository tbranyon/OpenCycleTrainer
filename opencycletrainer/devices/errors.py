"""Translate Bluetooth stack errors into short, actionable messages for riders.

Raw bleak / BlueZ / WinRT errors (``org.bluez.Error.InProgress``,
``le-connection-abort-by-local``, ``[WinError -2147020577]``...) are meaningless to most
users. Callers log the raw exception and show the text returned by
:func:`describe_ble_error` instead.
"""

from __future__ import annotations

import asyncio
from enum import Enum
import traceback

try:
    from bleak.exc import (
        BleakBluetoothNotAvailableError,
        BleakBluetoothNotAvailableReason,
        BleakDBusError,
        BleakDeviceNotFoundError,
    )
except ImportError:  # pragma: no cover - bleak is a hard dependency; keep messages usable without it
    BleakBluetoothNotAvailableError = BleakDBusError = BleakDeviceNotFoundError = ()  # type: ignore[assignment]
    BleakBluetoothNotAvailableReason = None  # type: ignore[assignment]


class BleOperation(Enum):
    """User-visible Bluetooth operations, with the verb phrase used in messages."""

    SCAN = "scan for devices"
    PAIR = "pair"
    UNPAIR = "unpair"
    CONNECT = "connect to"
    DISCONNECT = "disconnect"
    CALIBRATE = "calibrate"
    READ = "read from"
    SUBSCRIBE = "start receiving data from"


# Windows HRESULT for "The device is not ready for use" (0x8007048F), raised when the radio is off.
_WINERROR_DEVICE_NOT_READY = -2147020577

_BLUEZ_BUSY = {"org.bluez.Error.InProgress"}
_BLUEZ_UNAVAILABLE = {"org.bluez.Error.NotReady", "org.bluez.Error.NotAvailable"}
_BLUEZ_SERVICE_MISSING = {"org.freedesktop.DBus.Error.ServiceUnknown", "org.freedesktop.DBus.Error.NameHasNoOwner"}
_BLUEZ_REFUSED = {
    "org.bluez.Error.NotPermitted",
    "org.bluez.Error.NotAuthorized",
    "org.bluez.Error.AuthenticationFailed",
    "org.bluez.Error.AuthenticationRejected",
    "org.bluez.Error.AuthenticationCanceled",
}
_BLUEZ_NOT_FOUND = {"org.freedesktop.DBus.Error.UnknownObject", "org.bluez.Error.DoesNotExist"}
_BLUEZ_NOT_CONNECTED = {"org.bluez.Error.NotConnected"}

# Socket errors raised while opening the system D-Bus mean BlueZ (or D-Bus itself) is absent.
_DBUS_CONNECT_ERRORS = (FileNotFoundError, ConnectionRefusedError)
_DBUS_MODULE_MARKER = "dbus_fast"

_DENIED_REASON_NAMES = {"DENIED_BY_USER", "DENIED_BY_SYSTEM", "DENIED_BY_UNKNOWN"}

_UNAVAILABLE_PHRASES = ("no bluetooth adapters", "adapter not found", "bluetooth device is turned off", "powered off")
_NOT_CONNECTED_PHRASES = ("not connected",)
_NOT_FOUND_PHRASES = ("unreachable", "was not found")
_REFUSED_PHRASES = ("access denied",)

_BUSY = "Bluetooth is busy with another operation. Wait a moment and try again."
_UNAVAILABLE = "Bluetooth is off or unavailable. Turn Bluetooth on and try again."
_SERVICE_MISSING = (
    "The Bluetooth service isn't running. Start it (for example with "
    "'sudo systemctl start bluetooth') and try again."
)
_PERMISSION = (
    "This app doesn't have permission to use Bluetooth. Allow it in your system's "
    "privacy settings and try again."
)


def describe_ble_error(
    exc: BaseException,
    *,
    operation: BleOperation,
    device_name: str | None,
) -> str:
    """Return a plain-language explanation of *exc* for *operation* on *device_name*."""
    subject = device_name or "The device"
    obj = device_name or "the device"
    kind = _classify(exc)

    if kind == "timeout":
        return f"{subject} didn't respond. Make sure it's nearby and awake, then try again."
    if kind == "not_found":
        return (
            f"{subject} wasn't found. Make sure it's switched on and awake (pedal, or put it on), "
            "nearby, and not connected to another app or device."
        )
    if kind == "busy":
        return _BUSY
    if kind == "aborted":
        return (
            f"Couldn't {operation.value} {obj}. Wake the device and try again; if it keeps "
            "failing, switch it off and on."
        )
    if kind == "unavailable":
        return _UNAVAILABLE
    if kind == "service_missing":
        return _SERVICE_MISSING
    if kind == "permission":
        return _PERMISSION
    if kind == "refused":
        return (
            f"{subject} refused the connection. It may be in use by another app; "
            "disconnect it there and try again."
        )
    if kind == "not_connected":
        return f"{subject} isn't connected. Connect it and try again."
    if operation is BleOperation.SCAN:
        return "Couldn't scan for devices. Details were written to the log."
    return f"Couldn't {operation.value} {obj}. Details were written to the log."


def _classify(exc: BaseException) -> str | None:
    """Return a coarse error category for *exc*, or None when it is not recognised."""
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return "timeout"
    if BleakBluetoothNotAvailableError and isinstance(exc, BleakBluetoothNotAvailableError):
        reason = getattr(exc, "reason", None)
        return "permission" if getattr(reason, "name", "") in _DENIED_REASON_NAMES else "unavailable"
    if BleakDeviceNotFoundError and isinstance(exc, BleakDeviceNotFoundError):
        return "not_found"
    if BleakDBusError and isinstance(exc, BleakDBusError):
        dbus_kind = _classify_dbus(exc.dbus_error, exc.dbus_error_details or "")
        if dbus_kind is not None:
            return dbus_kind
    if isinstance(exc, OSError) and _winerror(exc) == _WINERROR_DEVICE_NOT_READY:
        return "unavailable"
    if isinstance(exc, _DBUS_CONNECT_ERRORS) and _raised_inside_dbus(exc):
        return "service_missing"
    return _classify_text(str(exc).lower())


def _classify_dbus(name: str, details: str) -> str | None:
    if name in _BLUEZ_BUSY:
        return "busy"
    if name in _BLUEZ_UNAVAILABLE:
        return "unavailable"
    if name in _BLUEZ_SERVICE_MISSING:
        return "service_missing"
    if name in _BLUEZ_REFUSED:
        return "refused"
    if name in _BLUEZ_NOT_FOUND:
        return "not_found"
    if name in _BLUEZ_NOT_CONNECTED:
        return "not_connected"
    if name == "org.bluez.Error.Failed":
        return "aborted"
    return None


def _classify_text(text: str) -> str | None:
    if any(phrase in text for phrase in _UNAVAILABLE_PHRASES):
        return "unavailable"
    if any(phrase in text for phrase in _NOT_CONNECTED_PHRASES):
        return "not_connected"
    if any(phrase in text for phrase in _NOT_FOUND_PHRASES):
        return "not_found"
    if any(phrase in text for phrase in _REFUSED_PHRASES):
        return "refused"
    return None


def _raised_inside_dbus(exc: BaseException) -> bool:
    """True when *exc* was raised from the D-Bus client library bleak uses on Linux."""
    return any(_DBUS_MODULE_MARKER in frame.filename for frame in traceback.extract_tb(exc.__traceback__))


def _winerror(exc: OSError) -> int | None:
    code = getattr(exc, "winerror", None)
    if code is not None:
        return code
    return exc.args[0] if exc.args and isinstance(exc.args[0], int) else None

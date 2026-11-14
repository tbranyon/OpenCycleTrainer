from __future__ import annotations

import asyncio

from bleak.exc import (
    BleakBluetoothNotAvailableError,
    BleakBluetoothNotAvailableReason,
    BleakDBusError,
    BleakDeviceNotFoundError,
    BleakError,
)

from opencycletrainer.devices.errors import BleOperation, describe_ble_error

_RAW_FRAGMENTS = ("org.bluez", "org.freedesktop", "le-connection", "WinError", "0x", "Traceback")


def _message(exc: BaseException, operation: BleOperation = BleOperation.CONNECT, name: str | None = "KICKR CORE") -> str:
    return describe_ble_error(exc, operation=operation, device_name=name)


def _assert_plain(message: str) -> None:
    for fragment in _RAW_FRAGMENTS:
        assert fragment not in message, f"raw error detail {fragment!r} leaked into: {message}"


def test_device_not_found_asks_user_to_wake_the_device():
    message = _message(BleakDeviceNotFoundError("AA:BB", "Device with address AA:BB was not found."))
    assert "KICKR CORE" in message
    assert "wasn't found" in message
    _assert_plain(message)


def test_timeout_says_the_device_did_not_respond():
    for exc in (asyncio.TimeoutError(), TimeoutError()):
        message = _message(exc)
        assert "didn't respond" in message
        _assert_plain(message)


def test_bluez_operation_in_progress_says_bluetooth_is_busy():
    message = _message(BleakDBusError("org.bluez.Error.InProgress", ["Operation already in progress"]))
    assert "busy" in message
    _assert_plain(message)


def test_bluez_connection_abort_suggests_retry():
    message = _message(BleakDBusError("org.bluez.Error.Failed", ["le-connection-abort-by-local"]))
    assert "Couldn't connect to KICKR CORE" in message
    _assert_plain(message)


def test_adapter_off_or_missing_says_bluetooth_is_unavailable():
    cases = [
        BleakDBusError("org.bluez.Error.NotReady", ["Resource Not Ready"]),
        BleakBluetoothNotAvailableError("off", BleakBluetoothNotAvailableReason.POWERED_OFF),
        BleakError("No Bluetooth adapters found."),
        OSError(-2147020577, "The device is not ready for use"),
    ]
    for exc in cases:
        message = _message(exc)
        assert "Bluetooth is off or unavailable" in message, message
        _assert_plain(message)


def test_bluetooth_service_not_running_on_linux():
    message = _message(BleakDBusError("org.freedesktop.DBus.Error.ServiceUnknown", ["The name org.bluez was not provided"]))
    assert "Bluetooth service isn't running" in message
    _assert_plain(message)


def test_permission_denied_explains_access():
    message = _message(BleakBluetoothNotAvailableError("denied", BleakBluetoothNotAvailableReason.DENIED_BY_USER))
    assert "permission" in message.lower()
    _assert_plain(message)


def test_windows_unreachable_is_treated_like_not_found():
    message = _message(BleakError("Could not get GATT services: Unreachable"))
    assert "wasn't found" in message or "didn't respond" in message
    _assert_plain(message)


def test_not_connected_errors_say_so():
    for exc in (BleakError("Not connected"), RuntimeError("Device AA:BB is not connected")):
        message = _message(exc, operation=BleOperation.CALIBRATE)
        assert "isn't connected" in message
        _assert_plain(message)


def test_unknown_error_falls_back_to_generic_message_with_operation_and_name():
    message = _message(ValueError("struct.error: unpack requires a buffer of 4 bytes"), operation=BleOperation.CALIBRATE)
    assert message == "Couldn't calibrate KICKR CORE. Details were written to the log."


def test_scan_errors_do_not_need_a_device_name():
    message = _message(BleakDBusError("org.bluez.Error.InProgress", []), operation=BleOperation.SCAN, name=None)
    assert "busy" in message
    assert "None" not in message


def test_missing_device_name_uses_generic_noun():
    message = _message(asyncio.TimeoutError(), name=None)
    assert "The device didn't respond" in message


def test_missing_system_bus_on_linux_says_bluetooth_service_is_not_running():
    """With no D-Bus/BlueZ, bleak fails with a bare FileNotFoundError from dbus_fast."""
    from dbus_fast.aio import MessageBus

    async def _connect_to_missing_bus() -> None:
        await MessageBus(bus_address="unix:path=/nonexistent/opencycletrainer-test-bus").connect()

    try:
        asyncio.run(_connect_to_missing_bus())
    except OSError as exc:
        raised = exc
    else:  # pragma: no cover - the socket path never exists
        raise AssertionError("expected the bus connection to fail")

    message = _message(raised, operation=BleOperation.SCAN, name=None)
    assert "Bluetooth service isn't running" in message
    _assert_plain(message)


def test_unrelated_missing_file_is_not_blamed_on_bluetooth():
    message = _message(FileNotFoundError(2, "No such file or directory"), operation=BleOperation.CALIBRATE)
    assert message == "Couldn't calibrate KICKR CORE. Details were written to the log."

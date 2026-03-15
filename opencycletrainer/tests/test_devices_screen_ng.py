"""Tests for NiceGUI devices screen logic (Phase 6)."""
from __future__ import annotations

import pytest

from opencycletrainer.devices.types import DeviceInfo, DeviceType
from opencycletrainer.ui.devices_screen_ng import (
    format_battery,
    get_status_variant,
    format_reading_text,
    DevicesController,
)
from opencycletrainer.devices.mock_backend import MockDeviceBackend


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _device(
    device_id: str = "test-id",
    name: str = "Test Device",
    device_type: DeviceType = DeviceType.TRAINER,
    connected: bool = False,
    paired: bool = True,
    battery_percent: int | None = None,
    supports_calibration: bool = False,
) -> DeviceInfo:
    return DeviceInfo(
        device_id=device_id,
        name=name,
        device_type=device_type,
        connected=connected,
        paired=paired,
        battery_percent=battery_percent,
        supports_calibration=supports_calibration,
    )


# ---------------------------------------------------------------------------
# format_battery
# ---------------------------------------------------------------------------


def test_format_battery_none_returns_unknown() -> None:
    assert format_battery(None) == "—"


def test_format_battery_value() -> None:
    assert format_battery(82) == "82%"


def test_format_battery_full() -> None:
    assert format_battery(100) == "100%"


def test_format_battery_low() -> None:
    assert format_battery(15) == "15%"


# ---------------------------------------------------------------------------
# get_status_variant
# ---------------------------------------------------------------------------


def test_status_variant_connected() -> None:
    device = _device(connected=True)
    assert get_status_variant(device) == "success"


def test_status_variant_disconnected() -> None:
    device = _device(connected=False)
    assert get_status_variant(device) == "neutral"


# ---------------------------------------------------------------------------
# format_reading_text
# ---------------------------------------------------------------------------


def test_format_reading_none_returns_dash() -> None:
    assert format_reading_text(None) == "—"


def test_format_reading_string_passthrough() -> None:
    assert format_reading_text("250 W") == "250 W"


# ---------------------------------------------------------------------------
# DevicesController
# ---------------------------------------------------------------------------


class TestDevicesController:
    """Tests for DevicesController — the logic layer without NiceGUI."""

    def setup_method(self) -> None:
        self.backend = MockDeviceBackend()
        self.controller = DevicesController(self.backend)

    def test_initial_paired_devices_populated(self) -> None:
        devices = self.controller.get_paired_devices()
        assert len(devices) > 0
        assert all(d.paired for d in devices)

    def test_initial_available_devices_populated(self) -> None:
        devices = self.controller.get_available_devices()
        assert len(devices) > 0
        assert all(not d.paired for d in devices)

    def test_pair_device_moves_to_paired(self) -> None:
        available = self.controller.get_available_devices()
        assert len(available) > 0
        target = available[0]
        future = self.controller.pair_device(target.device_id)
        future.result(timeout=1.0)
        paired_ids = [d.device_id for d in self.controller.get_paired_devices()]
        assert target.device_id in paired_ids

    def test_unpair_device_removes_from_paired(self) -> None:
        paired = self.controller.get_paired_devices()
        assert len(paired) > 0
        target = paired[0]
        future = self.controller.unpair_device(target.device_id)
        future.result(timeout=1.0)
        paired_ids = [d.device_id for d in self.controller.get_paired_devices()]
        assert target.device_id not in paired_ids

    def test_connect_device_marks_connected(self) -> None:
        # Find a paired but disconnected device
        paired = self.controller.get_paired_devices()
        disconnected = [d for d in paired if not d.connected]
        if not disconnected:
            pytest.skip("No disconnected paired devices in mock")
        target = disconnected[0]
        future = self.controller.connect_device(target.device_id)
        future.result(timeout=1.0)
        updated = next(
            d for d in self.controller.get_paired_devices() if d.device_id == target.device_id
        )
        assert updated.connected

    def test_disconnect_device_marks_disconnected(self) -> None:
        # Find a paired and connected device
        paired = self.controller.get_paired_devices()
        connected = [d for d in paired if d.connected]
        if not connected:
            pytest.skip("No connected paired devices in mock")
        target = connected[0]
        future = self.controller.disconnect_device(target.device_id)
        future.result(timeout=1.0)
        updated = next(
            d for d in self.controller.get_paired_devices() if d.device_id == target.device_id
        )
        assert not updated.connected

    def test_set_reading_stored(self) -> None:
        self.controller.set_reading("some-id", "250 W")
        assert self.controller.get_reading("some-id") == "250 W"

    def test_get_reading_missing_returns_dash(self) -> None:
        assert self.controller.get_reading("nonexistent") == "—"

    def test_get_connected_trainer_id_returns_trainer(self) -> None:
        # Mock backend has KICKR paired and connected
        trainer_id = self.controller.get_connected_trainer_id()
        assert trainer_id == "trainer-kickr"

    def test_get_connected_trainer_id_no_trainer_returns_none(self) -> None:
        # Disconnect all trainers
        for device in self.controller.get_paired_devices():
            if device.device_type == DeviceType.TRAINER and device.connected:
                self.controller.disconnect_device(device.device_id).result(timeout=1.0)
        assert self.controller.get_connected_trainer_id() is None

    def test_switch_backend(self) -> None:
        new_backend = MockDeviceBackend(devices=[])
        self.controller.switch_backend(new_backend)
        assert self.controller.get_paired_devices() == []

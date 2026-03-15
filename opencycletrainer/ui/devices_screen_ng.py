"""NiceGUI Devices Screen — Phase 6.

Ports DevicesScreen from PySide6 to NiceGUI, replacing QThread/Future callbacks
with asyncio and ui.timer polling.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from concurrent.futures import Future
from datetime import datetime, timezone

from nicegui import ui

from opencycletrainer.core.sensors import SensorSample
from opencycletrainer.devices.decoders import (
    CyclingPowerDecoder,
    CyclingSpeedCadenceDecoder,
    decode_heart_rate_measurement,
    decode_indoor_bike_data,
)
from opencycletrainer.devices.device_manager import DeviceManager
from opencycletrainer.devices.types import (
    CPS_MEASUREMENT_CHARACTERISTIC_UUID,
    CSC_MEASUREMENT_CHARACTERISTIC_UUID,
    DeviceInfo,
    DeviceType,
    FTMS_INDOOR_BIKE_DATA_CHARACTERISTIC_UUID,
    HRS_MEASUREMENT_CHARACTERISTIC_UUID,
)
from .components import screen_header, section_header, status_badge

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pure logic helpers (tested independently)
# ---------------------------------------------------------------------------


def format_battery(battery_percent: int | None) -> str:
    """Return a formatted battery string, or '—' if unknown."""
    if battery_percent is None:
        return "—"
    return f"{battery_percent}%"


def get_status_variant(device: DeviceInfo) -> str:
    """Return the badge variant for a device's connection status."""
    return "success" if device.connected else "neutral"


def format_reading_text(reading: str | None) -> str:
    """Return *reading* or '—' if None."""
    return reading if reading is not None else "—"


# ---------------------------------------------------------------------------
# DevicesController — pure logic layer (no NiceGUI)
# ---------------------------------------------------------------------------


class DevicesController:
    """Manages device state and wraps the DeviceManager for UI consumption.

    No NiceGUI imports — fully unit-testable.
    """

    def __init__(self, backend: DeviceManager) -> None:
        self._backend = backend
        self._current_readings: dict[str, str] = {}
        self._subscribed: set[str] = set()
        self._decoders: dict[str, CyclingPowerDecoder | CyclingSpeedCadenceDecoder] = {}
        self._calibrating: set[str] = set()
        self._calibration_offsets: dict[str, int | None] = {}
        self._on_sensor_sample_callbacks: list[Callable[[SensorSample], None]] = []
        self._on_trainer_changed_callbacks: list[Callable[[DeviceManager, str | None], None]] = []
        self._last_trainer_state: tuple[int, str | None] | None = None

    # ── Public interface ──────────────────────────────────────────────────

    @property
    def backend(self) -> DeviceManager:
        return self._backend

    def switch_backend(self, new_backend: DeviceManager) -> None:
        """Replace the active backend and clear all cached state."""
        self._backend.shutdown()
        self._backend = new_backend
        self._current_readings.clear()
        self._subscribed.clear()
        self._decoders.clear()
        self._calibrating.clear()
        self._calibration_offsets.clear()
        self._last_trainer_state = None

    def get_paired_devices(self) -> list[DeviceInfo]:
        return self._backend.get_paired_devices()

    def get_available_devices(self) -> list[DeviceInfo]:
        return self._backend.get_available_devices()

    def pair_device(self, device_id: str) -> Future:
        return self._backend.pair_device(device_id)

    def unpair_device(self, device_id: str) -> Future:
        return self._backend.unpair_device(device_id)

    def connect_device(self, device_id: str) -> Future:
        return self._backend.connect_device(device_id)

    def disconnect_device(self, device_id: str) -> Future:
        return self._backend.disconnect_device(device_id)

    def scan(self) -> Future:
        return self._backend.scan()

    def calibrate_device(self, device_id: str) -> Future:
        self._calibrating.add(device_id)
        return self._backend.calibrate_device(device_id)

    def on_calibration_complete(self, device_id: str, offset: int | None) -> None:
        self._calibrating.discard(device_id)
        self._calibration_offsets[device_id] = offset

    def on_calibration_error(self, device_id: str) -> None:
        self._calibrating.discard(device_id)

    def get_calibration_text(self, device: DeviceInfo) -> str:
        if device.device_type is not DeviceType.POWER_METER:
            return "N/A"
        if device.device_id in self._calibrating:
            return "Calibrating…"
        if device.device_id in self._calibration_offsets:
            offset = self._calibration_offsets[device.device_id]
            return f"Offset: {offset}" if offset is not None else "Calibrated"
        return "Not calibrated"

    def is_calibrating(self, device_id: str) -> bool:
        return device_id in self._calibrating

    def is_subscribed(self, device_id: str) -> bool:
        return device_id in self._subscribed

    def subscribe_device(self, device_id: str) -> Future:
        self._subscribed.add(device_id)
        return self._backend.subscribe_device_notifications(
            device_id, self._on_notification
        )

    def set_reading(self, device_id: str, text: str) -> None:
        self._current_readings[device_id] = text

    def get_reading(self, device_id: str) -> str:
        return self._current_readings.get(device_id, "—")

    def get_connected_trainer_id(self) -> str | None:
        for device in self._backend.get_paired_devices():
            if device.device_type is DeviceType.TRAINER and device.connected:
                return device.device_id
        return None

    def register_sensor_callback(self, cb: Callable[[SensorSample], None]) -> None:
        self._on_sensor_sample_callbacks.append(cb)

    def register_trainer_changed_callback(
        self, cb: Callable[[DeviceManager, str | None], None]
    ) -> None:
        self._on_trainer_changed_callbacks.append(cb)

    def check_trainer_changed(self) -> None:
        """Detect trainer connection changes and notify registered callbacks."""
        trainer_id = self.get_connected_trainer_id()
        current = (id(self._backend), trainer_id)
        if current != self._last_trainer_state:
            self._last_trainer_state = current
            for cb in self._on_trainer_changed_callbacks:
                try:
                    cb(self._backend, trainer_id)
                except Exception:
                    _logger.exception("Trainer-changed callback raised")

    # ── Notification decoder ──────────────────────────────────────────────

    def _on_notification(
        self, device_id: str, characteristic_uuid: str, payload: bytes
    ) -> None:
        now = datetime.now(timezone.utc)
        try:
            sample, reading_text = self._decode_notification(
                device_id, characteristic_uuid, payload, now
            )
        except Exception:
            return
        if sample is not None:
            for cb in self._on_sensor_sample_callbacks:
                try:
                    cb(sample)
                except Exception:
                    _logger.exception("Sensor sample callback raised")
        if reading_text is not None:
            self.set_reading(device_id, reading_text)

    def _decode_notification(
        self,
        device_id: str,
        characteristic_uuid: str,
        payload: bytes,
        now: object,
    ) -> tuple[SensorSample | None, str | None]:
        from datetime import datetime, timezone  # noqa: PLC0415

        ts = now if isinstance(now, datetime) else datetime.now(timezone.utc)

        if characteristic_uuid == CPS_MEASUREMENT_CHARACTERISTIC_UUID:
            if device_id not in self._decoders:
                self._decoders[device_id] = CyclingPowerDecoder()
            decoder = self._decoders[device_id]
            if not isinstance(decoder, CyclingPowerDecoder):
                return None, None
            metrics = decoder.decode(payload)
            sample = SensorSample(
                timestamp_utc=ts,
                source_characteristic_uuid=characteristic_uuid,
                power_watts=metrics.power_watts,
                cadence_rpm=metrics.cadence_rpm,
            )
            reading = f"{metrics.power_watts} W" if metrics.power_watts is not None else None
            return sample, reading

        if characteristic_uuid == FTMS_INDOOR_BIKE_DATA_CHARACTERISTIC_UUID:
            metrics = decode_indoor_bike_data(payload)
            sample = SensorSample(
                timestamp_utc=ts,
                source_characteristic_uuid=characteristic_uuid,
                power_watts=metrics.power_watts,
                cadence_rpm=metrics.cadence_rpm,
                speed_mps=metrics.speed_mps,
            )
            reading = f"{metrics.power_watts} W" if metrics.power_watts is not None else None
            return sample, reading

        if characteristic_uuid == HRS_MEASUREMENT_CHARACTERISTIC_UUID:
            metrics = decode_heart_rate_measurement(payload)
            sample = SensorSample(
                timestamp_utc=ts,
                source_characteristic_uuid=characteristic_uuid,
                heart_rate_bpm=metrics.heart_rate_bpm,
            )
            reading = f"{metrics.heart_rate_bpm} bpm" if metrics.heart_rate_bpm is not None else None
            return sample, reading

        if characteristic_uuid == CSC_MEASUREMENT_CHARACTERISTIC_UUID:
            if device_id not in self._decoders:
                self._decoders[device_id] = CyclingSpeedCadenceDecoder()
            decoder = self._decoders[device_id]
            if not isinstance(decoder, CyclingSpeedCadenceDecoder):
                return None, None
            metrics = decoder.decode(payload)
            sample = SensorSample(
                timestamp_utc=ts,
                source_characteristic_uuid=characteristic_uuid,
                cadence_rpm=metrics.cadence_rpm,
                speed_mps=metrics.speed_mps,
            )
            reading = f"{metrics.cadence_rpm:.0f} rpm" if metrics.cadence_rpm is not None else None
            return sample, reading

        return None, None


# ---------------------------------------------------------------------------
# DevicesScreenNg — NiceGUI view layer
# ---------------------------------------------------------------------------


class DevicesScreenNg:
    """NiceGUI devices screen: scan, pair, connect, calibrate BLE devices."""

    _REFRESH_INTERVAL_S = 1.5

    def __init__(
        self,
        controller: DevicesController,
        on_backend_changed: Callable[[str], None] | None = None,
    ) -> None:
        self._ctrl = controller
        self._on_backend_changed = on_backend_changed
        self._scanning = False

        actions = screen_header("Devices")
        with actions:
            self._scan_btn = (
                ui.button("Scan", icon="bluetooth_searching", on_click=self._on_scan_clicked)
                .classes("btn btn-primary btn-sm")
                .props("no-caps")
            )
            ui.label("Backend:").classes("text-label color-secondary").style("margin-left:12px")
            self._backend_select = ui.select(
                ["Mock", "Bleak"],
                value="Mock",
                on_change=self._on_backend_changed_handler,
            ).classes("devices-backend-select").props("dense outlined")

        # Status label
        with ui.element("div").style("padding: 4px 0 8px"):
            self._status_label = ui.label("Ready.").classes("text-small color-secondary")

        # Paired devices table
        section_header("Paired Devices")
        with ui.element("div").classes("devices-table-container"):
            self._paired_rows: ui.element = ui.element("div").classes("devices-table")
            self._paired_empty = ui.label("No paired devices.").classes(
                "placeholder-sub"
            ).style("padding: 16px")

        # Available devices table
        section_header("Available Devices")
        with ui.element("div").classes("devices-table-container"):
            self._available_rows: ui.element = ui.element("div").classes("devices-table")
            self._available_empty = ui.label(
                "No available devices found. Run a scan to discover devices."
            ).classes("placeholder-sub").style("padding: 16px")

        self._timer = ui.timer(self._REFRESH_INTERVAL_S, self._poll_refresh)
        self._refresh()

    # ── Polling ───────────────────────────────────────────────────────────

    def _poll_refresh(self) -> None:
        self._ctrl.check_trainer_changed()
        self._refresh()

    def _refresh(self) -> None:
        """Rebuild both device tables from current backend state."""
        paired = self._ctrl.get_paired_devices()
        available = self._ctrl.get_available_devices()

        # Subscribe to connected paired devices not yet subscribed
        for device in paired:
            if device.connected and not self._ctrl.is_subscribed(device.device_id):
                self._ctrl.subscribe_device(device.device_id)

        self._build_paired_table(paired)
        self._build_available_table(available)

    def _build_paired_table(self, devices: list[DeviceInfo]) -> None:
        self._paired_rows.clear()
        self._paired_empty.set_visibility(len(devices) == 0)
        with self._paired_rows:
            if devices:
                self._render_table_header()
            for device in devices:
                self._render_device_row(device, paired=True)

    def _build_available_table(self, devices: list[DeviceInfo]) -> None:
        self._available_rows.clear()
        self._available_empty.set_visibility(len(devices) == 0)
        with self._available_rows:
            if devices:
                self._render_table_header()
            for device in devices:
                self._render_device_row(device, paired=False)

    def _render_table_header(self) -> None:
        with ui.element("div").classes("devices-row devices-row-header"):
            ui.label("Name").classes("devices-col-name text-label color-secondary")
            ui.label("Type").classes("devices-col-type text-label color-secondary")
            ui.label("Status").classes("devices-col-status text-label color-secondary")
            ui.label("Battery").classes("devices-col-battery text-label color-secondary")
            ui.label("Reading").classes("devices-col-reading text-label color-secondary")
            ui.label("Actions").classes("devices-col-actions text-label color-secondary")

    def _render_device_row(self, device: DeviceInfo, *, paired: bool) -> None:
        with ui.element("div").classes("devices-row"):
            ui.label(device.name).classes("devices-col-name text-body")
            ui.label(device.device_type.label).classes("devices-col-type text-small color-secondary")

            with ui.element("div").classes("devices-col-status"):
                variant = get_status_variant(device)
                status_text = device.connection_status
                status_badge(status_text, variant)

            battery_text = format_battery(device.battery_percent)
            battery_cls = "devices-col-battery text-small"
            if device.battery_percent is not None and device.battery_percent <= 20:
                battery_cls += " color-warning"
            ui.label(battery_text).classes(battery_cls)

            reading = self._ctrl.get_reading(device.device_id)
            ui.label(format_reading_text(reading)).classes(
                "devices-col-reading text-small font-mono"
            )

            with ui.element("div").classes("devices-col-actions"):
                self._render_row_actions(device, paired=paired)

    def _render_row_actions(self, device: DeviceInfo, *, paired: bool) -> None:
        if paired:
            connect_label = "Disconnect" if device.connected else "Connect"
            connect_fn = (
                self._make_disconnect_handler(device.device_id)
                if device.connected
                else self._make_connect_handler(device.device_id)
            )
            ui.button(
                connect_label,
                on_click=connect_fn,
            ).classes("btn btn-secondary btn-sm").props("no-caps flat dense")

            ui.button(
                icon="delete",
                on_click=self._make_unpair_handler(device.device_id),
            ).classes("btn btn-destructive btn-sm").props("flat dense").tooltip("Unpair")

            if device.device_type is DeviceType.POWER_METER and device.supports_calibration:
                is_cal = self._ctrl.is_calibrating(device.device_id)
                cal_btn = ui.button(
                    "Calibrating…" if is_cal else "Calibrate",
                    on_click=self._make_calibrate_handler(device.device_id),
                ).classes("btn btn-secondary btn-sm").props("no-caps flat dense")
                if is_cal:
                    cal_btn.props(add="disabled")
        else:
            ui.button(
                "Pair",
                on_click=self._make_pair_handler(device.device_id),
            ).classes("btn btn-secondary btn-sm").props("no-caps flat dense")

    # ── Action handlers ───────────────────────────────────────────────────

    def _on_scan_clicked(self) -> None:
        asyncio.ensure_future(self._do_scan())

    async def _do_scan(self) -> None:
        self._scanning = True
        self._scan_btn.set_text("Scanning…")
        self._scan_btn.props(add="disabled")
        self._status_label.set_text("Scanning for BLE devices…")
        try:
            future = self._ctrl.scan()
            devices: list[DeviceInfo] = await asyncio.wrap_future(future)
            count = len(devices)
            self._status_label.set_text(f"Scan complete: {count} relevant device(s) found.")
        except Exception as exc:
            self._status_label.set_text(f"Scan failed: {exc}")
        finally:
            self._scanning = False
            self._scan_btn.set_text("Scan")
            self._scan_btn.props(remove="disabled")
            self._refresh()

    def _make_pair_handler(self, device_id: str) -> Callable:
        async def _handler() -> None:
            self._status_label.set_text(f"Pairing {device_id}…")
            try:
                await asyncio.wrap_future(self._ctrl.pair_device(device_id))
                self._status_label.set_text(f"Paired {device_id}.")
            except Exception as exc:
                self._status_label.set_text(f"Pair failed: {exc}")
            self._refresh()

        return _handler

    def _make_unpair_handler(self, device_id: str) -> Callable:
        async def _handler() -> None:
            self._status_label.set_text(f"Unpairing {device_id}…")
            try:
                await asyncio.wrap_future(self._ctrl.unpair_device(device_id))
                self._status_label.set_text(f"Unpaired {device_id}.")
            except Exception as exc:
                self._status_label.set_text(f"Unpair failed: {exc}")
            self._refresh()

        return _handler

    def _make_connect_handler(self, device_id: str) -> Callable:
        async def _handler() -> None:
            self._status_label.set_text(f"Connecting {device_id}…")
            try:
                await asyncio.wrap_future(self._ctrl.connect_device(device_id))
                self._status_label.set_text(f"Connected {device_id}.")
            except Exception as exc:
                self._status_label.set_text(f"Connect failed: {exc}")
            self._refresh()

        return _handler

    def _make_disconnect_handler(self, device_id: str) -> Callable:
        async def _handler() -> None:
            self._status_label.set_text(f"Disconnecting {device_id}…")
            try:
                await asyncio.wrap_future(self._ctrl.disconnect_device(device_id))
                self._status_label.set_text(f"Disconnected {device_id}.")
            except Exception as exc:
                self._status_label.set_text(f"Disconnect failed: {exc}")
            self._refresh()

        return _handler

    def _make_calibrate_handler(self, device_id: str) -> Callable:
        async def _handler() -> None:
            self._status_label.set_text(f"Calibrating {device_id}…")
            self._refresh()
            try:
                future = self._ctrl.calibrate_device(device_id)
                offset: int | None = await asyncio.wrap_future(future)
                self._ctrl.on_calibration_complete(device_id, offset)
                msg = (
                    f"Calibration complete for {device_id}: offset {offset}."
                    if offset is not None
                    else f"Calibration complete for {device_id}."
                )
                self._status_label.set_text(msg)
            except Exception as exc:
                self._ctrl.on_calibration_error(device_id)
                self._status_label.set_text(f"Calibration failed for {device_id}: {exc}")
            self._refresh()

        return _handler

    def _on_backend_changed_handler(self, e: object) -> None:
        value = getattr(e, "value", None) or "Mock"
        if self._on_backend_changed:
            self._on_backend_changed(value)

    def shutdown(self) -> None:
        """Stop the polling timer."""
        self._timer.cancel()

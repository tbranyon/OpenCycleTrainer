from __future__ import annotations

from collections.abc import Callable
import logging
import threading
from concurrent.futures import CancelledError, Future
from functools import partial
from typing import Any

from PySide6.QtCore import Qt, QTimer, Signal, Slot
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from opencycletrainer.core.control.ftms_control import FTMSControl
from opencycletrainer.core.sensors import SensorSample
from opencycletrainer.devices.ble_backend import BleakDeviceBackend, BleakFTMSControlTransport
from opencycletrainer.devices.mock_backend import MockDeviceBackend, MockFTMSControlTransport
from opencycletrainer.storage.paired_devices import PairedDeviceStore
from opencycletrainer.devices.decoders import (
    CyclingPowerDecoder,
    CyclingSpeedCadenceDecoder,
    decode_heart_rate_measurement,
    decode_indoor_bike_data,
)
from opencycletrainer.devices.decoders.ftms import (
    FTMSCapabilities,
    decode_ftms_fitness_machine_features,
    decode_ftms_supported_power_range,
    decode_resistance_level_range,
)
from opencycletrainer.devices.decoders.cps import (
    CPSCapabilities,
    decode_cps_features,
    decode_cps_sensor_location,
)
from opencycletrainer.devices.decoders.hrs import (
    HRSCapabilities,
    decode_hrs_body_sensor_location,
)
from opencycletrainer.devices.device_manager import DeviceManager
from opencycletrainer.devices.errors import BleOperation, describe_ble_error
from opencycletrainer.devices.types import (
    CPS_FEATURE_CHARACTERISTIC_UUID,
    CPS_MEASUREMENT_CHARACTERISTIC_UUID,
    CPS_SENSOR_LOCATION_CHARACTERISTIC_UUID,
    CSC_MEASUREMENT_CHARACTERISTIC_UUID,
    DeviceInfo,
    DeviceType,
    FTMS_FITNESS_MACHINE_FEATURE_CHARACTERISTIC_UUID,
    FTMS_INDOOR_BIKE_DATA_CHARACTERISTIC_UUID,
    FTMS_RESISTANCE_LEVEL_RANGE_CHARACTERISTIC_UUID,
    FTMS_SUPPORTED_POWER_RANGE_CHARACTERISTIC_UUID,
    HRS_BODY_SENSOR_LOCATION_CHARACTERISTIC_UUID,
    HRS_MEASUREMENT_CHARACTERISTIC_UUID,
)

_logger = logging.getLogger(__name__)

_CALIBRATION_NOT_CALIBRATED = "Not calibrated"
_CALIBRATION_NA = "N/A"
_BATTERY_UNKNOWN = "—"
_BATTERY_UNREPORTED_TOOLTIP = "This device doesn't report a battery level."
_DETAILS_TOOLTIP = "Double-click for device details."
_BUSY_INDICATOR_WIDTH = 120
_SCAN_LABEL = "Scan"
_SCANNING_LABEL = "Scanning…"
_PAIRED_EMPTY_TEXT = (
    "No paired devices yet. Wake your trainer and sensors (pedal, or put the strap on), "
    "press Scan, then Pair each one."
)
_AVAILABLE_EMPTY_TEXT = "Press Scan to look for nearby devices."
_AVAILABLE_EMPTY_AFTER_SCAN_TEXT = (
    "No new devices found. Make sure they're awake and not connected to another app or device."
)
_STATUS_TEXT_BY_PENDING = {
    BleOperation.CONNECT: "Connecting…",
    BleOperation.DISCONNECT: "Disconnecting…",
    BleOperation.UNPAIR: "Unpairing…",
}

_COL_NAME = 0
_COL_TYPE = 1
_COL_STATUS = 2
_COL_BATTERY = 3
_COL_READING = 4
_COL_CALIBRATION = 5
_COL_ACTIONS = 6
_NUM_COLS = 7


class DevicesScreen(QWidget):
    action_succeeded = Signal(object, object)
    sensor_sample_received = Signal(object)  # SensorSample
    trainer_device_changed = Signal(object, object)  # (backend, trainer_device_id | None)
    power_source_pair_changed = Signal(object, object)  # (trainer_device_id | None, power_meter_device_id | None)
    opentrueup_availability_changed = Signal(bool)  # True when PM + trainer both connected
    device_connected = Signal(str)  # device name, emitted on successful autoconnect
    _reading_received = Signal(str, str)  # (device_id, reading_text)
    _spin_down_ready = Signal(str, str, object, object)  # (device_id, name, control, transport)
    _spin_down_error = Signal(str)  # error message from spin-down preparation
    _capabilities_ready = Signal(str, object)  # (device_name, FTMSCapabilities)
    _hrs_capabilities_ready = Signal(str, object)  # (device_name, HRSCapabilities)
    _cps_capabilities_ready = Signal(str, object)  # (device_name, CPSCapabilities)
    _device_connection_changed = Signal(str, bool)  # (device_id, connected) from BLE thread
    _devices_changed = Signal()  # backend state changed on another thread

    def __init__(
        self,
        backend: DeviceManager | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._backend = backend if backend is not None else BleakDeviceBackend(paired_device_store=PairedDeviceStore())

        self._calibrating: set[str] = set()
        self._calibration_offsets: dict[str, int | None] = {}
        self._current_readings: dict[str, str] = {}
        self._reading_items: dict[str, QTableWidgetItem] = {}
        self._subscribed_devices: set[str] = set()
        self._decoders: dict[str, CyclingPowerDecoder | CyclingSpeedCadenceDecoder] = {}
        self._last_trainer_selection: tuple[int, str | None] | None = None
        self._last_power_source_pair: tuple[str | None, str | None] | None = None
        self._last_opentrueup_available: bool | None = None
        self._paired_device_ids: list[str] = []
        self._spin_down_dialog: Any = None
        self._spin_down_device_id: str | None = None
        self._pending: dict[str, BleOperation] = {}
        self._scanning = False
        self._has_scanned = False
        self._refresh_scheduled = False
        self.confirm_unpair: Callable[[DeviceInfo], bool] = self._confirm_unpair_dialog

        self.action_succeeded.connect(self._handle_action_succeeded)
        self._reading_received.connect(self._on_reading_received)
        self._spin_down_ready.connect(self._show_spin_down_dialog)
        self._spin_down_error.connect(self._on_spin_down_error)
        self.sensor_sample_received.connect(self._forward_speed_to_spin_down)
        self._capabilities_ready.connect(self._show_ftms_capabilities_dialog)
        self._hrs_capabilities_ready.connect(self._show_hrs_capabilities_dialog)
        self._cps_capabilities_ready.connect(self._show_cps_capabilities_dialog)
        self._device_connection_changed.connect(self._on_device_connection_changed)
        self._devices_changed.connect(self._schedule_refresh)
        self._backend.device_connection_changed_callback = self._on_device_connection_changed_background
        self._backend.devices_changed_callback = self._devices_changed.emit

        layout = QVBoxLayout(self)
        title = QLabel("Devices")
        title.setObjectName("devicesScreenTitle")
        layout.addWidget(title)

        controls_layout = QHBoxLayout()
        self.scan_button = QPushButton(_SCAN_LABEL, self)
        self.scan_button.clicked.connect(self._scan_devices)
        controls_layout.addWidget(self.scan_button)
        self.busy_indicator = QProgressBar(self)
        self.busy_indicator.setRange(0, 0)
        self.busy_indicator.setTextVisible(False)
        self.busy_indicator.setMaximumWidth(_BUSY_INDICATOR_WIDTH)
        self.busy_indicator.setHidden(True)
        controls_layout.addWidget(self.busy_indicator)
        controls_layout.addStretch(1)
        layout.addLayout(controls_layout)

        self.status_label = QLabel("Ready.")
        self.status_label.setObjectName("devicesStatusLabel")
        layout.addWidget(self.status_label)

        self.paired_table = self._create_table()
        self.paired_table.cellDoubleClicked.connect(self._on_paired_table_double_clicked)
        paired_group = QGroupBox("Paired Devices")
        paired_layout = QVBoxLayout(paired_group)
        paired_layout.addWidget(self.paired_table)
        self.paired_empty_label = QLabel(_PAIRED_EMPTY_TEXT, paired_group)
        self.paired_empty_label.setWordWrap(True)
        paired_layout.addWidget(self.paired_empty_label)
        layout.addWidget(paired_group)

        self.available_table = self._create_table()
        available_group = QGroupBox("Available Devices")
        available_layout = QVBoxLayout(available_group)
        available_layout.addWidget(self.available_table)
        self.available_empty_label = QLabel(_AVAILABLE_EMPTY_TEXT, available_group)
        self.available_empty_label.setWordWrap(True)
        available_layout.addWidget(self.available_empty_label)
        layout.addWidget(available_group)

        self.refresh()

    def closeEvent(self, event: Any) -> None:  # noqa: N802
        self._backend.shutdown()
        super().closeEvent(event)

    def refresh(self) -> None:
        paired = self._backend.get_paired_devices()
        available = self._backend.get_available_devices()
        self._populate_paired_table(paired)
        self._populate_available_table(available)
        self.paired_empty_label.setHidden(bool(paired))
        self.available_empty_label.setText(
            _AVAILABLE_EMPTY_AFTER_SCAN_TEXT if self._has_scanned and not self._scanning else _AVAILABLE_EMPTY_TEXT
        )
        self.available_empty_label.setHidden(bool(available))
        self.busy_indicator.setHidden(not self._is_busy(paired))
        self._emit_trainer_device_change(paired)

    def _is_busy(self, paired: list[DeviceInfo]) -> bool:
        if self._scanning or self._pending:
            return True
        return any(device.connecting or device.reconnecting for device in paired)

    @Slot()
    def _schedule_refresh(self) -> None:
        """Coalesce bursts of backend notifications into a single table rebuild."""
        if self._refresh_scheduled:
            return
        self._refresh_scheduled = True
        QTimer.singleShot(0, self._run_scheduled_refresh)

    def _run_scheduled_refresh(self) -> None:
        self._refresh_scheduled = False
        self.refresh()

    @property
    def backend(self) -> DeviceManager:
        return self._backend

    def connected_trainer_device_id(self) -> str | None:
        for device in self._backend.get_paired_devices():
            if device.device_type is DeviceType.TRAINER and device.connected:
                return device.device_id
        return None

    def connected_heart_rate_device_id(self) -> str | None:
        for device in self._backend.get_paired_devices():
            if device.device_type is DeviceType.HEART_RATE and device.connected:
                return device.device_id
        return None

    def connected_power_meter_device_id(self) -> str | None:
        for device in self._backend.get_paired_devices():
            if device.device_type is DeviceType.POWER_METER and device.connected:
                return device.device_id
        return None

    def has_opentrueup_devices(self) -> bool:
        """Return True when both a power meter and a trainer are connected."""
        paired = self._backend.get_paired_devices()
        has_trainer = any(d.device_type is DeviceType.TRAINER and d.connected for d in paired)
        has_power_meter = any(d.device_type is DeviceType.POWER_METER and d.connected for d in paired)
        return has_trainer and has_power_meter

    def _create_table(self) -> QTableWidget:
        table = QTableWidget(0, _NUM_COLS, self)
        table.setHorizontalHeaderLabels(
            ["Name", "Type", "Status", "Battery", "Current Reading", "Calibration", "Actions"]
        )
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionMode(QTableWidget.NoSelection)
        table.setAlternatingRowColors(True)
        header = table.horizontalHeader()
        header.setStretchLastSection(True)
        return table

    def start_autoconnect(self) -> None:
        """Begin connecting to previously paired devices without user intervention.

        Runs in the background; on completion the paired table refreshes and a
        device_connected signal fires for each device that came online."""
        self.status_label.setText("Connecting to paired devices…")
        self._submit_future(
            self._backend.autoconnect_paired_devices(),
            on_success=self._on_autoconnect_complete,
            operation=BleOperation.CONNECT,
        )

    def _on_autoconnect_complete(self, connected_ids: object) -> None:
        self.refresh()
        if not isinstance(connected_ids, list):
            return
        paired = {device.device_id: device for device in self._backend.get_paired_devices()}
        connected_count = 0
        for device_id in connected_ids:
            device = paired.get(device_id)
            if device is not None and device.connected:
                self.device_connected.emit(device.name)
                connected_count += 1
        if connected_count:
            self.status_label.setText(f"Connected to {connected_count} paired device(s).")
        else:
            self.status_label.setText(
                "No paired devices connected." if paired else "Ready. Press Scan to find your devices."
            )

    def _scan_devices(self) -> None:
        if self._scanning:
            return
        self._scanning = True
        self.scan_button.setText(_SCANNING_LABEL)
        self.scan_button.setEnabled(False)
        self.status_label.setText("Scanning for devices… Make sure they're awake.")
        self.refresh()
        self._submit_future(
            self._backend.scan(),
            on_success=self._on_scan_complete,
            on_failure=self._on_scan_failed,
            operation=BleOperation.SCAN,
        )

    def _finish_scan(self) -> None:
        self._scanning = False
        self._has_scanned = True
        self.scan_button.setText(_SCAN_LABEL)
        self.scan_button.setEnabled(True)
        self.refresh()

    def _on_scan_complete(self, devices: list[DeviceInfo]) -> None:
        self._finish_scan()
        self.status_label.setText(f"Scan complete: found {len(devices)} device(s).")

    def _on_scan_failed(self, message: str) -> None:
        self._finish_scan()
        self.status_label.setText(message)

    def _populate_paired_table(self, devices: list[DeviceInfo]) -> None:
        self._reading_items.clear()
        self._paired_device_ids = [device.device_id for device in devices]
        self.paired_table.setRowCount(len(devices))
        for row, device in enumerate(devices):
            pending = self._pending.get(device.device_id)
            status_text = _STATUS_TEXT_BY_PENDING.get(pending, device.connection_status) if pending else device.connection_status
            self._set_device_row(self.paired_table, row, device, status_text=status_text)

            action_widget = QWidget(self.paired_table)
            action_layout = QHBoxLayout(action_widget)
            action_layout.setContentsMargins(0, 0, 0, 0)
            action_layout.setSpacing(6)

            winding_down = pending in (BleOperation.DISCONNECT, BleOperation.UNPAIR)
            connecting = pending is BleOperation.CONNECT or device.connecting or device.reconnecting
            if connecting and not winding_down:
                connect_text, connect_action = "Cancel", self._cancel_connect
            elif device.connected:
                connect_text, connect_action = "Disconnect", self._disconnect_device
            else:
                connect_text, connect_action = "Connect", self._connect_device
            connect_button = QPushButton(connect_text, action_widget)
            connect_button.setEnabled(not winding_down)
            connect_button.clicked.connect(partial(connect_action, device.device_id))
            action_layout.addWidget(connect_button)

            unpair_button = QPushButton("Unpair", action_widget)
            unpair_button.setEnabled(not winding_down)
            unpair_button.clicked.connect(partial(self._unpair_device, device.device_id))
            action_layout.addWidget(unpair_button)

            if device.device_type is DeviceType.POWER_METER and device.supports_calibration:
                is_calibrating = device.device_id in self._calibrating
                calibrate_button = QPushButton(
                    "Calibrating..." if is_calibrating else "Calibrate",
                    action_widget,
                )
                calibrate_button.setEnabled(not is_calibrating)
                calibrate_button.clicked.connect(partial(self._calibrate_device, device.device_id))
                action_layout.addWidget(calibrate_button)

            if device.device_type is DeviceType.TRAINER and device.connected:
                spin_down_button = QPushButton("Spin-Down", action_widget)
                spin_down_button.clicked.connect(
                    partial(self._open_spin_down_dialog, device.device_id)
                )
                action_layout.addWidget(spin_down_button)

            action_layout.addStretch(1)
            self.paired_table.setCellWidget(row, _COL_ACTIONS, action_widget)

            if device.connected and device.device_id not in self._subscribed_devices:
                self._subscribe_device(device.device_id)

        self.paired_table.resizeColumnsToContents()

    def _populate_available_table(self, devices: list[DeviceInfo]) -> None:
        self.available_table.setRowCount(len(devices))
        for row, device in enumerate(devices):
            self._set_device_row(self.available_table, row, device)

            action_widget = QWidget(self.available_table)
            action_layout = QHBoxLayout(action_widget)
            action_layout.setContentsMargins(0, 0, 0, 0)
            action_layout.setSpacing(6)

            pair_button = QPushButton("Pair", action_widget)
            pair_button.clicked.connect(partial(self._pair_device, device.device_id))
            action_layout.addWidget(pair_button)
            action_layout.addStretch(1)
            self.available_table.setCellWidget(row, _COL_ACTIONS, action_widget)

        self.available_table.resizeColumnsToContents()

    def _set_device_row(
        self,
        table: QTableWidget,
        row: int,
        device: DeviceInfo,
        *,
        status_text: str | None = None,
    ) -> None:
        name_item = QTableWidgetItem(device.name)
        if table is self.paired_table and device.connected:
            name_item.setToolTip(_DETAILS_TOOLTIP)
        table.setItem(row, _COL_NAME, name_item)
        table.setItem(row, _COL_TYPE, QTableWidgetItem(device.device_type.label))
        table.setItem(row, _COL_STATUS, QTableWidgetItem(status_text or device.connection_status))

        battery_text = f"{device.battery_percent}%" if device.battery_percent is not None else _BATTERY_UNKNOWN
        battery_item = QTableWidgetItem(battery_text)
        battery_item.setTextAlignment(Qt.AlignCenter)
        if device.battery_percent is None and device.connected:
            battery_item.setToolTip(_BATTERY_UNREPORTED_TOOLTIP)
        table.setItem(row, _COL_BATTERY, battery_item)

        reading_text = self._current_readings.get(device.device_id, "--")
        reading_item = QTableWidgetItem(reading_text)
        reading_item.setTextAlignment(Qt.AlignCenter)
        table.setItem(row, _COL_READING, reading_item)
        if table is self.paired_table:
            self._reading_items[device.device_id] = reading_item

        if device.device_type is DeviceType.POWER_METER:
            if device.device_id in self._calibration_offsets:
                offset = self._calibration_offsets[device.device_id]
                calibration_text = f"Offset: {offset}" if offset is not None else "Calibrated"
            else:
                calibration_text = _CALIBRATION_NOT_CALIBRATED
        else:
            calibration_text = _CALIBRATION_NA
        calibration_item = QTableWidgetItem(calibration_text)
        calibration_item.setTextAlignment(Qt.AlignCenter)
        table.setItem(row, _COL_CALIBRATION, calibration_item)

    def _subscribe_device(self, device_id: str) -> None:
        self._subscribed_devices.add(device_id)
        self._submit_future(
            self._backend.subscribe_device_notifications(device_id, self._on_notification),
            on_success=lambda _: None,
            operation=BleOperation.SUBSCRIBE,
            device_id=device_id,
        )

    def _on_notification(self, device_id: str, characteristic_uuid: str, payload: bytes) -> None:
        from datetime import datetime, timezone
        try:
            sensor_sample, reading_text = self._decode_notification(
                device_id, characteristic_uuid, payload, datetime.now(timezone.utc)
            )
        except Exception:
            return
        if sensor_sample is not None:
            self.sensor_sample_received.emit(sensor_sample)
        if reading_text is not None:
            self._reading_received.emit(device_id, reading_text)

    def _decode_notification(
        self,
        device_id: str,
        characteristic_uuid: str,
        payload: bytes,
        received_at_utc: object,
    ) -> tuple[SensorSample | None, str | None]:
        from datetime import datetime, timezone
        now = received_at_utc if isinstance(received_at_utc, datetime) else datetime.now(timezone.utc)

        if characteristic_uuid == CPS_MEASUREMENT_CHARACTERISTIC_UUID:
            if device_id not in self._decoders:
                self._decoders[device_id] = CyclingPowerDecoder()
            decoder = self._decoders[device_id]
            if not isinstance(decoder, CyclingPowerDecoder):
                return None, None
            metrics = decoder.decode(payload)
            sample = SensorSample(
                timestamp_utc=now,
                source_characteristic_uuid=characteristic_uuid,
                device_id=device_id,
                power_watts=metrics.power_watts,
                cadence_rpm=metrics.cadence_rpm,
                accumulated_energy_kj=metrics.accumulated_energy_kj,
                pedal_balance_left_pct=metrics.pedal_balance_left_pct,
            )
            reading_text = f"{metrics.power_watts} W" if metrics.power_watts is not None else None
            return sample, reading_text

        if characteristic_uuid == FTMS_INDOOR_BIKE_DATA_CHARACTERISTIC_UUID:
            metrics = decode_indoor_bike_data(payload)
            sample = SensorSample(
                timestamp_utc=now,
                source_characteristic_uuid=characteristic_uuid,
                device_id=device_id,
                power_watts=metrics.power_watts,
                cadence_rpm=metrics.cadence_rpm,
                speed_mps=metrics.speed_mps,
                heart_rate_bpm=metrics.heart_rate_bpm,
                accumulated_energy_kj=metrics.accumulated_energy_kj,
            )
            reading_text = f"{metrics.power_watts} W" if metrics.power_watts is not None else None
            return sample, reading_text

        if characteristic_uuid == HRS_MEASUREMENT_CHARACTERISTIC_UUID:
            metrics = decode_heart_rate_measurement(payload)
            sample = SensorSample(
                timestamp_utc=now,
                source_characteristic_uuid=characteristic_uuid,
                device_id=device_id,
                heart_rate_bpm=metrics.heart_rate_bpm,
                rr_intervals_ms=metrics.rr_intervals_ms,
            )
            reading_text = f"{metrics.heart_rate_bpm} bpm" if metrics.heart_rate_bpm is not None else None
            return sample, reading_text

        if characteristic_uuid == CSC_MEASUREMENT_CHARACTERISTIC_UUID:
            if device_id not in self._decoders:
                self._decoders[device_id] = CyclingSpeedCadenceDecoder()
            decoder = self._decoders[device_id]
            if not isinstance(decoder, CyclingSpeedCadenceDecoder):
                return None, None
            metrics = decoder.decode(payload)
            sample = SensorSample(
                timestamp_utc=now,
                source_characteristic_uuid=characteristic_uuid,
                device_id=device_id,
                cadence_rpm=metrics.cadence_rpm,
                speed_mps=metrics.speed_mps,
            )
            reading_text = f"{metrics.cadence_rpm:.0f} rpm" if metrics.cadence_rpm is not None else None
            return sample, reading_text

        return None, None

    @Slot(str, str)
    def _on_reading_received(self, device_id: str, reading_text: str) -> None:
        self._current_readings[device_id] = reading_text
        if device_id in self._reading_items:
            self._reading_items[device_id].setText(reading_text)

    def _pair_device(self, device_id: str) -> None:
        name = self._device_name(device_id)
        self.status_label.setText(f"Pairing {name}…")
        self._submit_future(
            self._backend.pair_device(device_id),
            on_success=lambda _: self._on_paired(device_id),
            operation=BleOperation.PAIR,
            device_id=device_id,
        )

    def _on_paired(self, device_id: str) -> None:
        """Connect a newly paired device straight away; pairing alone is rarely the goal."""
        self.refresh()
        self._connect_device(device_id)

    def _unpair_device(self, device_id: str) -> None:
        device = self._find_device(device_id)
        if device is not None and not self.confirm_unpair(device):
            return
        name = self._device_name(device_id)
        self._pending[device_id] = BleOperation.UNPAIR
        self.status_label.setText(f"Unpairing {name}…")
        self.refresh()
        self._submit_future(
            self._backend.unpair_device(device_id),
            on_success=lambda _: self._finish_pending(device_id, f"Unpaired {name}."),
            operation=BleOperation.UNPAIR,
            device_id=device_id,
        )

    def _confirm_unpair_dialog(self, device: DeviceInfo) -> bool:
        answer = QMessageBox.question(
            self,
            "Unpair device",
            f"Unpair {device.name}? You'll need to scan and pair it again to use it.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        return answer == QMessageBox.Yes

    def _connect_device(self, device_id: str) -> None:
        name = self._device_name(device_id)
        self._pending[device_id] = BleOperation.CONNECT
        self.status_label.setText(f"Connecting to {name}…")
        self.refresh()
        self._submit_future(
            self._backend.connect_device(device_id),
            on_success=lambda _: self._finish_pending(device_id, f"Connected to {name}.", only=BleOperation.CONNECT),
            on_cancel=lambda: self._finish_pending(device_id, None, only=BleOperation.CONNECT),
            operation=BleOperation.CONNECT,
            device_id=device_id,
        )

    def _cancel_connect(self, device_id: str) -> None:
        """Stop a connect or reconnect that is still in progress."""
        name = self._device_name(device_id)
        self._pending[device_id] = BleOperation.DISCONNECT
        self.status_label.setText(f"Stopping connection to {name}…")
        self.refresh()
        self._submit_future(
            self._backend.disconnect_device(device_id),
            on_success=lambda _: self._finish_pending(device_id, f"Stopped connecting to {name}."),
            operation=BleOperation.DISCONNECT,
            device_id=device_id,
        )

    def _disconnect_device(self, device_id: str) -> None:
        name = self._device_name(device_id)
        self._pending[device_id] = BleOperation.DISCONNECT
        self.status_label.setText(f"Disconnecting {name}…")
        self.refresh()
        self._submit_future(
            self._backend.disconnect_device(device_id),
            on_success=lambda _: self._finish_pending(device_id, f"Disconnected {name}."),
            operation=BleOperation.DISCONNECT,
            device_id=device_id,
        )

    def _finish_pending(
        self,
        device_id: str,
        message: str | None,
        *,
        only: BleOperation | None = None,
    ) -> None:
        """Clear *device_id*'s in-progress marker (if it is still *only*) and show *message*."""
        if only is None or self._pending.get(device_id) is only:
            self._pending.pop(device_id, None)
        elif message is not None:
            # A newer action (e.g. Cancel) superseded this one; let it report instead.
            return
        self.refresh()
        if message is not None:
            self.status_label.setText(message)

    def _device_name(self, device_id: str) -> str:
        device = self._find_device(device_id)
        return device.name if device is not None else device_id

    def _find_device(self, device_id: str) -> DeviceInfo | None:
        for device in [*self._backend.get_paired_devices(), *self._backend.get_available_devices()]:
            if device.device_id == device_id:
                return device
        return None

    def _calibrate_device(self, device_id: str) -> None:
        self.status_label.setText(f"Calibrating {self._device_name(device_id)}…")
        self._calibrating.add(device_id)
        self.refresh()

        future = self._backend.calibrate_device(device_id)

        def _on_done(completed: Future) -> None:  # type: ignore[type-arg]
            try:
                offset = completed.result()
                self.action_succeeded.emit(
                    lambda o: self._on_calibration_complete(device_id, o),
                    offset,
                )
            except Exception as exc:
                _logger.warning("Calibration failed for '%s'", device_id, exc_info=exc)
                message = describe_ble_error(
                    exc, operation=BleOperation.CALIBRATE, device_name=self._device_name(device_id)
                )
                self.action_succeeded.emit(
                    lambda _: self._on_calibration_error(device_id, message),
                    None,
                )

        future.add_done_callback(_on_done)

    def _on_calibration_complete(self, device_id: str, offset: int | None) -> None:
        self._calibrating.discard(device_id)
        self._calibration_offsets[device_id] = offset
        self.refresh()
        name = self._device_name(device_id)
        if offset is not None:
            self.status_label.setText(f"Calibration complete for {name}: offset {offset}.")
        else:
            self.status_label.setText(f"Calibration complete for {name}.")

    def _on_calibration_error(self, device_id: str, message: str) -> None:
        self._calibrating.discard(device_id)
        self.refresh()
        self.status_label.setText(message)

    def _open_spin_down_dialog(self, device_id: str) -> None:
        """Prepare an FTMS control session off-thread, then show the spin-down dialog."""
        device = next(
            (d for d in self._backend.get_paired_devices() if d.device_id == device_id),
            None,
        )
        device_name = device.name if device is not None else device_id
        self.status_label.setText(f"Preparing spin-down for {device_name}...")
        threading.Thread(
            target=self._prepare_spin_down,
            args=(device_id, device_name),
            daemon=True,
        ).start()

    def _prepare_spin_down(self, device_id: str, device_name: str) -> None:
        transport = self._create_spin_down_transport(device_id)
        if transport is None:
            self._spin_down_error.emit("Spin-down is not available for this trainer.")
            return
        try:
            control = FTMSControl(transport)
        except Exception:
            self._spin_down_error.emit(f"Could not connect to {device_name} for spin-down.")
            return
        self._spin_down_ready.emit(device_id, device_name, control, transport)

    def _create_spin_down_transport(self, device_id: str) -> object | None:
        if isinstance(self._backend, BleakDeviceBackend):
            return BleakFTMSControlTransport(self._backend, device_id)
        if isinstance(self._backend, MockDeviceBackend):
            return MockFTMSControlTransport()
        return None

    @Slot(str)
    def _on_spin_down_error(self, message: str) -> None:
        self.status_label.setText(message)

    @Slot(str, str, object, object)
    def _show_spin_down_dialog(
        self,
        device_id: str,
        device_name: str,
        control: object,
        transport: object,
    ) -> None:
        from opencycletrainer.core.control.spin_down import SpinDownController
        from opencycletrainer.ui.spin_down_dialog import SpinDownDialog

        def factory(status_callback):
            return SpinDownController(
                control,
                subscribe_status=transport.subscribe_status,
                status_callback=status_callback,
            )

        dialog = SpinDownDialog(device_name, factory, parent=self)
        self._spin_down_dialog = dialog
        self._spin_down_device_id = device_id
        self.status_label.setText(f"Spin-down ready for {device_name}.")
        try:
            dialog.exec()
        finally:
            self._spin_down_dialog = None
            self._spin_down_device_id = None
        self.status_label.setText(f"Spin-down closed for {device_name}.")

    @Slot(object)
    def _forward_speed_to_spin_down(self, sample: object) -> None:
        dialog = self._spin_down_dialog
        if dialog is None:
            return
        if getattr(sample, "device_id", None) != self._spin_down_device_id:
            return
        speed_mps = getattr(sample, "speed_mps", None)
        if speed_mps is None:
            return
        dialog.update_current_speed(speed_mps * 3.6)

    @Slot(int, int)
    def _on_paired_table_double_clicked(self, row: int, col: int) -> None:  # noqa: ARG002
        if row >= len(self._paired_device_ids):
            return
        device_id = self._paired_device_ids[row]
        paired = self._backend.get_paired_devices()
        device = next((d for d in paired if d.device_id == device_id), None)
        if device is None or not device.connected:
            return
        self.status_label.setText(f"Reading capabilities for {device.name}...")
        if device.device_type is DeviceType.TRAINER:
            threading.Thread(
                target=self._fetch_and_show_capabilities,
                args=(device_id, device.name),
                daemon=True,
            ).start()
        elif device.device_type is DeviceType.HEART_RATE:
            threading.Thread(
                target=self._fetch_and_show_hrs_capabilities,
                args=(device_id, device.name),
                daemon=True,
            ).start()
        elif device.device_type is DeviceType.POWER_METER:
            threading.Thread(
                target=self._fetch_and_show_cps_capabilities,
                args=(device_id, device.name),
                daemon=True,
            ).start()

    def _fetch_and_show_capabilities(self, device_id: str, device_name: str) -> None:
        """Background thread: reads FTMS capability characteristics and emits result."""
        features = None
        power_range = None
        resistance_range = None
        try:
            data = self._backend.read_gatt_characteristic(
                device_id, FTMS_FITNESS_MACHINE_FEATURE_CHARACTERISTIC_UUID
            ).result(timeout=5.0)
            features = decode_ftms_fitness_machine_features(data)
        except Exception:
            pass
        try:
            data = self._backend.read_gatt_characteristic(
                device_id, FTMS_SUPPORTED_POWER_RANGE_CHARACTERISTIC_UUID
            ).result(timeout=5.0)
            power_range = decode_ftms_supported_power_range(data)
        except Exception:
            pass
        try:
            data = self._backend.read_gatt_characteristic(
                device_id, FTMS_RESISTANCE_LEVEL_RANGE_CHARACTERISTIC_UUID
            ).result(timeout=5.0)
            resistance_range = decode_resistance_level_range(data)
        except Exception:
            pass
        capabilities = FTMSCapabilities(
            features=features,
            power_range=power_range,
            resistance_range=resistance_range,
        )
        self._capabilities_ready.emit(device_name, capabilities)

    @Slot(str, object)
    def _show_ftms_capabilities_dialog(self, device_name: str, capabilities: object) -> None:
        from opencycletrainer.ui.ftms_capabilities_dialog import FTMSCapabilitiesDialog
        dialog = FTMSCapabilitiesDialog(device_name, capabilities, parent=self)  # type: ignore[arg-type]
        dialog.exec()
        self.status_label.setText(f"Capabilities displayed for {device_name}.")

    def _fetch_and_show_hrs_capabilities(self, device_id: str, device_name: str) -> None:
        """Background thread: reads HRS capability characteristics and emits result."""
        body_sensor_location = None
        try:
            data = self._backend.read_gatt_characteristic(
                device_id, HRS_BODY_SENSOR_LOCATION_CHARACTERISTIC_UUID
            ).result(timeout=5.0)
            body_sensor_location = decode_hrs_body_sensor_location(data)
        except Exception:
            pass
        capabilities = HRSCapabilities(body_sensor_location=body_sensor_location)
        self._hrs_capabilities_ready.emit(device_name, capabilities)

    @Slot(str, object)
    def _show_hrs_capabilities_dialog(self, device_name: str, capabilities: object) -> None:
        from opencycletrainer.ui.hrs_capabilities_dialog import HRSCapabilitiesDialog
        dialog = HRSCapabilitiesDialog(device_name, capabilities, parent=self)  # type: ignore[arg-type]
        dialog.exec()
        self.status_label.setText(f"Capabilities displayed for {device_name}.")

    def _fetch_and_show_cps_capabilities(self, device_id: str, device_name: str) -> None:
        """Background thread: reads CPS capability characteristics and emits result."""
        features = None
        sensor_location = None
        try:
            data = self._backend.read_gatt_characteristic(
                device_id, CPS_FEATURE_CHARACTERISTIC_UUID
            ).result(timeout=5.0)
            features = decode_cps_features(data)
        except Exception:
            pass
        try:
            data = self._backend.read_gatt_characteristic(
                device_id, CPS_SENSOR_LOCATION_CHARACTERISTIC_UUID
            ).result(timeout=5.0)
            sensor_location = decode_cps_sensor_location(data)
        except Exception:
            pass
        capabilities = CPSCapabilities(features=features, sensor_location=sensor_location)
        self._cps_capabilities_ready.emit(device_name, capabilities)

    @Slot(str, object)
    def _show_cps_capabilities_dialog(self, device_name: str, capabilities: object) -> None:
        from opencycletrainer.ui.cps_capabilities_dialog import CPSCapabilitiesDialog
        dialog = CPSCapabilitiesDialog(device_name, capabilities, parent=self)  # type: ignore[arg-type]
        dialog.exec()
        self.status_label.setText(f"Capabilities displayed for {device_name}.")

    def _submit_future(
        self,
        future: Future[Any],
        *,
        on_success: Any,
        operation: BleOperation,
        device_id: str | None = None,
        on_failure: Callable[[str], None] | None = None,
        on_cancel: Callable[[], None] | None = None,
    ) -> None:
        """Run the matching handler on the Qt thread once *future* finishes.

        Failures are logged with the raw exception and shown to the user as a plain-language
        message; by default that also clears *device_id*'s in-progress marker.
        """
        device_name = self._device_name(device_id) if device_id is not None else None

        def _default_failure(message: str) -> None:
            if device_id is not None:
                self._pending.pop(device_id, None)
                self.refresh()
            self.status_label.setText(message)

        failure_handler = on_failure or _default_failure

        def _on_done(completed: Future[Any]) -> None:
            try:
                result = completed.result()
            except CancelledError:
                if on_cancel is not None:
                    self.action_succeeded.emit(lambda _: on_cancel(), None)
                return
            except Exception as exc:
                _logger.warning("%s failed for %s", operation.name.lower(), device_id or "devices", exc_info=exc)
                message = describe_ble_error(exc, operation=operation, device_name=device_name)
                self.action_succeeded.emit(lambda _: failure_handler(message), None)
                return
            self.action_succeeded.emit(on_success, result)

        future.add_done_callback(_on_done)

    @Slot(object, object)
    def _handle_action_succeeded(self, on_success: Any, result: Any) -> None:
        if callable(on_success):
            on_success(result)

    def _on_device_connection_changed_background(self, device_id: str, connected: bool) -> None:
        """Called from the BLE background thread when a device connects or disconnects.
        Forwards to the main thread via a queued signal."""
        self._device_connection_changed.emit(device_id, connected)

    @Slot(str, bool)
    def _on_device_connection_changed(self, device_id: str, connected: bool) -> None:
        """Handles a device connection-state change on the Qt main thread.
        Removes the subscription record on disconnect so re-subscription happens on reconnect."""
        if not connected:
            self._subscribed_devices.discard(device_id)
        self.refresh()

    def _emit_trainer_device_change(self, paired_devices: list[DeviceInfo]) -> None:
        trainer_id: str | None = None
        power_meter_id: str | None = None
        for device in paired_devices:
            if device.device_type is DeviceType.TRAINER and device.connected:
                trainer_id = device.device_id
            if device.device_type is DeviceType.POWER_METER and device.connected:
                power_meter_id = device.device_id

        selection = (id(self._backend), trainer_id)
        if selection != self._last_trainer_selection:
            self._last_trainer_selection = selection
            self.trainer_device_changed.emit(self._backend, trainer_id)

        power_source_pair = (trainer_id, power_meter_id)
        if power_source_pair != self._last_power_source_pair:
            self._last_power_source_pair = power_source_pair
            self.power_source_pair_changed.emit(trainer_id, power_meter_id)

        opentrueup_available = trainer_id is not None and power_meter_id is not None
        if opentrueup_available != self._last_opentrueup_available:
            self._last_opentrueup_available = opentrueup_available
            self.opentrueup_availability_changed.emit(opentrueup_available)

from __future__ import annotations

import threading
from concurrent.futures import Future
from functools import partial
from typing import Any

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from opencycletrainer.core.sensors import SensorSample
from opencycletrainer.devices.ble_backend import BleakDeviceBackend
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
from opencycletrainer.devices.device_manager import DeviceManager
from opencycletrainer.devices.types import (
    CPS_MEASUREMENT_CHARACTERISTIC_UUID,
    CSC_MEASUREMENT_CHARACTERISTIC_UUID,
    DeviceInfo,
    DeviceType,
    FTMS_FITNESS_MACHINE_FEATURE_CHARACTERISTIC_UUID,
    FTMS_INDOOR_BIKE_DATA_CHARACTERISTIC_UUID,
    FTMS_RESISTANCE_LEVEL_RANGE_CHARACTERISTIC_UUID,
    FTMS_SUPPORTED_POWER_RANGE_CHARACTERISTIC_UUID,
    HRS_MEASUREMENT_CHARACTERISTIC_UUID,
)

_CALIBRATION_NOT_CALIBRATED = "Not calibrated"
_CALIBRATION_NA = "N/A"

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
    action_failed = Signal(str)
    sensor_sample_received = Signal(object)  # SensorSample
    trainer_device_changed = Signal(object, object)  # (backend, trainer_device_id | None)
    opentrueup_availability_changed = Signal(bool)  # True when PM + trainer both connected
    _reading_received = Signal(str, str)  # (device_id, reading_text)
    _capabilities_ready = Signal(str, object)  # (device_name, FTMSCapabilities)
    _device_connection_changed = Signal(str, bool)  # (device_id, connected) from BLE thread

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
        self._last_opentrueup_available: bool | None = None
        self._paired_device_ids: list[str] = []

        self.action_succeeded.connect(self._handle_action_succeeded)
        self.action_failed.connect(self._handle_action_failed)
        self._reading_received.connect(self._on_reading_received)
        self._capabilities_ready.connect(self._show_ftms_capabilities_dialog)
        self._device_connection_changed.connect(self._on_device_connection_changed)
        if isinstance(self._backend, BleakDeviceBackend):
            self._backend.device_connection_changed_callback = self._on_device_connection_changed_background

        layout = QVBoxLayout(self)
        title = QLabel("Devices")
        title.setObjectName("devicesScreenTitle")
        layout.addWidget(title)

        controls_layout = QHBoxLayout()
        self.scan_button = QPushButton("Scan", self)
        self.scan_button.clicked.connect(self._scan_devices)
        controls_layout.addWidget(self.scan_button)
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
        layout.addWidget(paired_group)

        self.available_table = self._create_table()
        available_group = QGroupBox("Available Devices")
        available_layout = QVBoxLayout(available_group)
        available_layout.addWidget(self.available_table)
        layout.addWidget(available_group)

        self.refresh()

    def closeEvent(self, event: Any) -> None:  # noqa: N802
        self._backend.shutdown()
        super().closeEvent(event)

    def refresh(self) -> None:
        paired = self._backend.get_paired_devices()
        self._populate_paired_table(paired)
        self._populate_available_table(self._backend.get_available_devices())
        self._emit_trainer_device_change(paired)

    @property
    def backend(self) -> DeviceManager:
        return self._backend

    def connected_trainer_device_id(self) -> str | None:
        for device in self._backend.get_paired_devices():
            if device.device_type is DeviceType.TRAINER and device.connected:
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

    def _scan_devices(self) -> None:
        self.status_label.setText("Scanning for BLE devices...")
        self._submit_future(
            self._backend.scan(),
            on_success=self._on_scan_complete,
            error_prefix="Scan failed",
        )

    def _on_scan_complete(self, devices: list[DeviceInfo]) -> None:
        self.refresh()
        self.status_label.setText(f"Scan complete: {len(devices)} relevant device(s).")

    def _populate_paired_table(self, devices: list[DeviceInfo]) -> None:
        self._reading_items.clear()
        self._paired_device_ids = [device.device_id for device in devices]
        self.paired_table.setRowCount(len(devices))
        for row, device in enumerate(devices):
            self._set_device_row(self.paired_table, row, device)

            action_widget = QWidget(self.paired_table)
            action_layout = QHBoxLayout(action_widget)
            action_layout.setContentsMargins(0, 0, 0, 0)
            action_layout.setSpacing(6)

            connect_text = "Disconnect" if device.connected else "Connect"
            connect_action = self._disconnect_device if device.connected else self._connect_device
            connect_button = QPushButton(connect_text, action_widget)
            connect_button.clicked.connect(partial(connect_action, device.device_id))
            action_layout.addWidget(connect_button)

            unpair_button = QPushButton("Unpair", action_widget)
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

    def _set_device_row(self, table: QTableWidget, row: int, device: DeviceInfo) -> None:
        table.setItem(row, _COL_NAME, QTableWidgetItem(device.name))
        table.setItem(row, _COL_TYPE, QTableWidgetItem(device.device_type.label))
        table.setItem(row, _COL_STATUS, QTableWidgetItem(device.connection_status))

        battery_text = f"{device.battery_percent}%" if device.battery_percent is not None else "Unknown"
        battery_item = QTableWidgetItem(battery_text)
        battery_item.setTextAlignment(Qt.AlignCenter)
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
            error_prefix=f"Subscribe failed for {device_id}",
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
                power_watts=metrics.power_watts,
                cadence_rpm=metrics.cadence_rpm,
            )
            reading_text = f"{metrics.power_watts} W" if metrics.power_watts is not None else None
            return sample, reading_text

        if characteristic_uuid == FTMS_INDOOR_BIKE_DATA_CHARACTERISTIC_UUID:
            metrics = decode_indoor_bike_data(payload)
            sample = SensorSample(
                timestamp_utc=now,
                source_characteristic_uuid=characteristic_uuid,
                power_watts=metrics.power_watts,
                cadence_rpm=metrics.cadence_rpm,
                speed_mps=metrics.speed_mps,
            )
            reading_text = f"{metrics.power_watts} W" if metrics.power_watts is not None else None
            return sample, reading_text

        if characteristic_uuid == HRS_MEASUREMENT_CHARACTERISTIC_UUID:
            metrics = decode_heart_rate_measurement(payload)
            sample = SensorSample(
                timestamp_utc=now,
                source_characteristic_uuid=characteristic_uuid,
                heart_rate_bpm=metrics.heart_rate_bpm,
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
        self.status_label.setText(f"Pairing {device_id}...")
        self._submit_future(
            self._backend.pair_device(device_id),
            on_success=lambda _: self._post_action_refresh(f"Paired {device_id}."),
            error_prefix=f"Pair failed for {device_id}",
        )

    def _unpair_device(self, device_id: str) -> None:
        self.status_label.setText(f"Unpairing {device_id}...")
        self._submit_future(
            self._backend.unpair_device(device_id),
            on_success=lambda _: self._post_action_refresh(f"Unpaired {device_id}."),
            error_prefix=f"Unpair failed for {device_id}",
        )

    def _connect_device(self, device_id: str) -> None:
        self.status_label.setText(f"Connecting {device_id}...")
        self._submit_future(
            self._backend.connect_device(device_id),
            on_success=lambda _: self._post_action_refresh(f"Connected {device_id}."),
            error_prefix=f"Connect failed for {device_id}",
        )

    def _disconnect_device(self, device_id: str) -> None:
        self.status_label.setText(f"Disconnecting {device_id}...")
        self._submit_future(
            self._backend.disconnect_device(device_id),
            on_success=lambda _: self._post_action_refresh(f"Disconnected {device_id}."),
            error_prefix=f"Disconnect failed for {device_id}",
        )

    def _calibrate_device(self, device_id: str) -> None:
        self.status_label.setText(f"Calibrating {device_id}...")
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
                self.action_succeeded.emit(
                    lambda _: self._on_calibration_error(device_id, str(exc)),
                    None,
                )

        future.add_done_callback(_on_done)

    def _on_calibration_complete(self, device_id: str, offset: int | None) -> None:
        self._calibrating.discard(device_id)
        self._calibration_offsets[device_id] = offset
        self.refresh()
        if offset is not None:
            self.status_label.setText(f"Calibration complete for {device_id}: offset {offset}.")
        else:
            self.status_label.setText(f"Calibration complete for {device_id}.")

    def _on_calibration_error(self, device_id: str, message: str) -> None:
        self._calibrating.discard(device_id)
        self.refresh()
        self.status_label.setText(f"Calibration failed for {device_id}: {message}")

    def _post_action_refresh(self, message: str) -> None:
        self.refresh()
        self.status_label.setText(message)

    @Slot(int, int)
    def _on_paired_table_double_clicked(self, row: int, col: int) -> None:  # noqa: ARG002
        if row >= len(self._paired_device_ids):
            return
        device_id = self._paired_device_ids[row]
        paired = self._backend.get_paired_devices()
        device = next((d for d in paired if d.device_id == device_id), None)
        if device is None or not device.connected or device.device_type is not DeviceType.TRAINER:
            return
        self.status_label.setText(f"Reading capabilities for {device.name}...")
        threading.Thread(
            target=self._fetch_and_show_capabilities,
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

    def _submit_future(
        self,
        future: Future[Any],
        *,
        on_success: Any,
        error_prefix: str,
    ) -> None:
        def _on_done(completed: Future[Any]) -> None:
            try:
                result = completed.result()
            except Exception as exc:
                self.action_failed.emit(f"{error_prefix}: {exc}")
                return
            self.action_succeeded.emit(on_success, result)

        future.add_done_callback(_on_done)

    @Slot(object, object)
    def _handle_action_succeeded(self, on_success: Any, result: Any) -> None:
        if callable(on_success):
            on_success(result)

    @Slot(str)
    def _handle_action_failed(self, message: str) -> None:
        self.status_label.setText(message)

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
        has_power_meter = False
        for device in paired_devices:
            if device.device_type is DeviceType.TRAINER and device.connected:
                trainer_id = device.device_id
            if device.device_type is DeviceType.POWER_METER and device.connected:
                has_power_meter = True

        selection = (id(self._backend), trainer_id)
        if selection != self._last_trainer_selection:
            self._last_trainer_selection = selection
            self.trainer_device_changed.emit(self._backend, trainer_id)

        opentrueup_available = trainer_id is not None and has_power_meter
        if opentrueup_available != self._last_opentrueup_available:
            self._last_opentrueup_available = opentrueup_available
            self.opentrueup_availability_changed.emit(opentrueup_available)

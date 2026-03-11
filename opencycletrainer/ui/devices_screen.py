from __future__ import annotations

from concurrent.futures import Future
from functools import partial
from typing import Any

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from opencycletrainer.devices.ble_backend import BleakDeviceBackend
from opencycletrainer.devices.device_manager import DeviceManager
from opencycletrainer.devices.mock_backend import MockDeviceBackend
from opencycletrainer.devices.types import DeviceInfo, DeviceType


class DevicesScreen(QWidget):
    action_succeeded = Signal(object, object)
    action_failed = Signal(str)

    def __init__(
        self,
        backend: DeviceManager | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._backend = backend if backend is not None else MockDeviceBackend()

        self.action_succeeded.connect(self._handle_action_succeeded)
        self.action_failed.connect(self._handle_action_failed)

        layout = QVBoxLayout(self)
        title = QLabel("Devices")
        title.setObjectName("devicesScreenTitle")
        layout.addWidget(title)

        controls_layout = QHBoxLayout()
        controls_layout.addWidget(QLabel("Backend:"))
        self.backend_selector = QComboBox(self)
        self.backend_selector.addItems(["Mock", "Bleak"])
        if isinstance(self._backend, BleakDeviceBackend):
            self.backend_selector.setCurrentText("Bleak")
        else:
            self.backend_selector.setCurrentText("Mock")
        controls_layout.addWidget(self.backend_selector)

        self.scan_button = QPushButton("Scan", self)
        self.scan_button.clicked.connect(self._scan_devices)
        controls_layout.addWidget(self.scan_button)
        controls_layout.addStretch(1)
        layout.addLayout(controls_layout)

        self.status_label = QLabel("Ready.")
        self.status_label.setObjectName("devicesStatusLabel")
        layout.addWidget(self.status_label)

        self.paired_table = self._create_table()
        paired_group = QGroupBox("Paired Devices")
        paired_layout = QVBoxLayout(paired_group)
        paired_layout.addWidget(self.paired_table)
        layout.addWidget(paired_group)

        self.available_table = self._create_table()
        available_group = QGroupBox("Available Devices")
        available_layout = QVBoxLayout(available_group)
        available_layout.addWidget(self.available_table)
        layout.addWidget(available_group)

        self.backend_selector.currentTextChanged.connect(self._switch_backend)
        self.refresh()

    def closeEvent(self, event: Any) -> None:  # noqa: N802
        self._backend.shutdown()
        super().closeEvent(event)

    def refresh(self) -> None:
        self._populate_paired_table(self._backend.get_paired_devices())
        self._populate_available_table(self._backend.get_available_devices())

    def _create_table(self) -> QTableWidget:
        table = QTableWidget(0, 5, self)
        table.setHorizontalHeaderLabels(["Name", "Type", "Status", "Battery", "Actions"])
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionMode(QTableWidget.NoSelection)
        table.setAlternatingRowColors(True)
        header = table.horizontalHeader()
        header.setStretchLastSection(True)
        return table

    def _switch_backend(self, backend_name: str) -> None:
        if backend_name == "Mock" and isinstance(self._backend, MockDeviceBackend):
            return
        if backend_name == "Bleak" and isinstance(self._backend, BleakDeviceBackend):
            return

        self._backend.shutdown()
        if backend_name == "Bleak":
            self._backend = BleakDeviceBackend()
        else:
            self._backend = MockDeviceBackend()

        self.status_label.setText(f"Using {backend_name} backend.")
        self.refresh()

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
                calibrate_button = QPushButton("Calibrate", action_widget)
                calibrate_button.setEnabled(True)
                calibrate_button.clicked.connect(partial(self._calibrate_device, device.device_id))
                action_layout.addWidget(calibrate_button)

            action_layout.addStretch(1)
            self.paired_table.setCellWidget(row, 4, action_widget)

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
            self.available_table.setCellWidget(row, 4, action_widget)

        self.available_table.resizeColumnsToContents()

    def _set_device_row(self, table: QTableWidget, row: int, device: DeviceInfo) -> None:
        table.setItem(row, 0, QTableWidgetItem(device.name))
        table.setItem(row, 1, QTableWidgetItem(device.device_type.label))
        table.setItem(row, 2, QTableWidgetItem(device.connection_status))
        battery_text = f"{device.battery_percent}%" if device.battery_percent is not None else "Unknown"
        battery_item = QTableWidgetItem(battery_text)
        battery_item.setTextAlignment(Qt.AlignCenter)
        table.setItem(row, 3, battery_item)

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
        self._submit_future(
            self._backend.calibrate_device(device_id),
            on_success=lambda supported: self._on_calibration_result(device_id, supported),
            error_prefix=f"Calibration failed for {device_id}",
        )

    def _on_calibration_result(self, device_id: str, supported: bool) -> None:
        self.refresh()
        if supported:
            self.status_label.setText(f"Calibration command sent to {device_id}.")
        else:
            self.status_label.setText(f"Calibration not supported for {device_id}.")

    def _post_action_refresh(self, message: str) -> None:
        self.refresh()
        self.status_label.setText(message)

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

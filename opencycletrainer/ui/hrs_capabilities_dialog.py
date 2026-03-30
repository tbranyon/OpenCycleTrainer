from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from opencycletrainer.devices.decoders.hrs import HRSCapabilities

_NA = "N/A"


class HRSCapabilitiesDialog(QDialog):
    """Modal dialog that shows the capabilities of a connected heart rate monitor."""

    def __init__(self, device_name: str, capabilities: HRSCapabilities, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Capabilities: {device_name}")
        self.setModal(True)
        self.setMinimumWidth(360)

        outer = QVBoxLayout(self)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setSpacing(12)

        layout.addWidget(self._build_info_group(capabilities))
        layout.addStretch(1)

        scroll.setWidget(content)
        outer.addWidget(scroll)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.accept)
        outer.addWidget(buttons)

    def _build_info_group(self, capabilities: HRSCapabilities) -> QGroupBox:
        group = QGroupBox("Sensor Information")
        form = QFormLayout(group)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)

        if capabilities.body_sensor_location is not None:
            location_text = capabilities.body_sensor_location.label
        else:
            location_text = _NA
        location_label = QLabel(location_text)
        location_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        form.addRow("Body Sensor Location:", location_label)

        return group

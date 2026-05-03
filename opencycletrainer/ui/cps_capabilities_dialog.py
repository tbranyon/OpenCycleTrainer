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

from opencycletrainer.devices.decoders.cps import CPSCapabilities

_YES = "Yes"
_NO = "No"
_NA = "N/A"


class CPSCapabilitiesDialog(QDialog):
    """Modal dialog that shows the capabilities of a connected CPS power meter."""

    def __init__(self, device_name: str, capabilities: CPSCapabilities, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Capabilities: {device_name}")
        self.setModal(True)
        self.setMinimumWidth(400)

        outer = QVBoxLayout(self)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setSpacing(12)

        layout.addWidget(self._build_info_group(capabilities))
        layout.addWidget(self._build_features_group(capabilities))
        layout.addStretch(1)

        scroll.setWidget(content)
        outer.addWidget(scroll)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.accept)
        outer.addWidget(buttons)

    def _build_info_group(self, capabilities: CPSCapabilities) -> QGroupBox:
        group = QGroupBox("Sensor Information")
        form = QFormLayout(group)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)

        if capabilities.sensor_location is not None:
            location_text = capabilities.sensor_location.label
        else:
            location_text = _NA
        location_label = QLabel(location_text)
        location_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        form.addRow("Sensor Location:", location_label)

        return group

    def _build_features_group(self, capabilities: CPSCapabilities) -> QGroupBox:
        group = QGroupBox("Power Meter Features")
        form = QFormLayout(group)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)

        if capabilities.features is None:
            na_label = QLabel(_NA)
            na_label.setAlignment(Qt.AlignmentFlag.AlignRight)
            form.addRow("Features:", na_label)
            return group

        context_label = QLabel(capabilities.features.measurement_context)
        context_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        form.addRow("Measurement Context:", context_label)

        for name, supported in capabilities.features.all_feature_labels():
            val_label = QLabel(_YES if supported else _NO)
            val_label.setAlignment(Qt.AlignmentFlag.AlignRight)
            form.addRow(name + ":", val_label)

        return group

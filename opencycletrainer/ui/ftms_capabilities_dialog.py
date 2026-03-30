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

from opencycletrainer.devices.decoders.ftms import FTMSCapabilities

_YES = "Yes"
_NO = "No"
_NA = "N/A"


class FTMSCapabilitiesDialog(QDialog):
    """Modal dialog that shows the capabilities of a connected FTMS trainer."""

    def __init__(self, device_name: str, capabilities: FTMSCapabilities, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Capabilities: {device_name}")
        self.setModal(True)
        self.setMinimumWidth(420)

        outer = QVBoxLayout(self)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setSpacing(12)

        if capabilities.features is not None:
            layout.addWidget(self._build_features_group(capabilities.features))
        else:
            lbl = QLabel(_NA)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(QGroupBox("Fitness Machine Features"))
            layout.addWidget(lbl)

        layout.addWidget(self._build_ranges_group(capabilities))
        layout.addStretch(1)

        scroll.setWidget(content)
        outer.addWidget(scroll)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.accept)
        outer.addWidget(buttons)

    def _build_features_group(self, features: object) -> QGroupBox:
        from opencycletrainer.devices.decoders.ftms import FTMSFeatures
        assert isinstance(features, FTMSFeatures)

        group = QGroupBox("Fitness Machine Features")
        form = QFormLayout(group)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)

        for name, supported in features.all_feature_labels():
            val_label = QLabel(_YES if supported else _NO)
            val_label.setAlignment(Qt.AlignmentFlag.AlignRight)
            form.addRow(name + ":", val_label)

        target_group = QGroupBox("Target Setting Features")
        target_form = QFormLayout(target_group)
        target_form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)

        for name, supported in features.all_target_setting_labels():
            val_label = QLabel(_YES if supported else _NO)
            val_label.setAlignment(Qt.AlignmentFlag.AlignRight)
            target_form.addRow(name + ":", val_label)

        wrapper = QGroupBox("Features")
        wrapper_layout = QVBoxLayout(wrapper)
        wrapper_layout.addWidget(group)
        wrapper_layout.addWidget(target_group)
        return wrapper

    def _build_ranges_group(self, capabilities: FTMSCapabilities) -> QGroupBox:
        group = QGroupBox("Supported Ranges")
        form = QFormLayout(group)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)

        if capabilities.power_range is not None:
            pr = capabilities.power_range
            text = f"{pr.minimum_watts} – {pr.maximum_watts} W (increment: {pr.minimum_increment_watts} W)"
        else:
            text = _NA
        form.addRow("Power Range:", QLabel(text))

        if capabilities.resistance_range is not None:
            rr = capabilities.resistance_range
            text = (
                f"{rr.minimum:.1f} – {rr.maximum:.1f}"
                f" (increment: {rr.minimum_increment:.1f}, {rr.step_count} steps)"
            )
        else:
            text = _NA
        form.addRow("Resistance Range:", QLabel(text))

        return group

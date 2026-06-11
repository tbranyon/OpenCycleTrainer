from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Signal, Slot
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from opencycletrainer.core.control.spin_down import SpinDownPhase, SpinDownState

_PHASE_MESSAGES = {
    SpinDownPhase.IDLE: "Press Start to begin spin-down calibration.",
    SpinDownPhase.STARTING: "Requesting calibration from the trainer…",
    SpinDownPhase.SPIN_UP: "Increase your speed into the target band and hold it.",
    SpinDownPhase.STOP_PEDALING: "Stop pedaling now and let the wheel coast down.",
    SpinDownPhase.SUCCESS: "Calibration complete.",
    SpinDownPhase.ERROR: "Calibration failed.",
}

_IN_BAND_STYLE = "color: #2e7d32; font-weight: bold;"
_NORMAL_STYLE = ""

# Builds a controller wired to deliver progress via the supplied callback.
SpinDownControllerFactory = Callable[[Callable[[SpinDownState], None]], object]


class SpinDownDialog(QDialog):
    """Guided modal dialog that walks the user through FTMS spin-down calibration."""

    _state_received = Signal(object)  # SpinDownState

    def __init__(
        self,
        device_name: str,
        controller_factory: SpinDownControllerFactory,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Spin-Down Calibration: {device_name}")
        self.setModal(True)
        self.setMinimumWidth(400)

        self._target_low_kmh: float | None = None
        self._target_high_kmh: float | None = None

        layout = QVBoxLayout(self)

        instructions = QLabel(
            "Spin-down calibration measures how your trainer coasts to a stop so its power "
            "readings stay accurate. Warm up the trainer for a few minutes, then press Start."
        )
        instructions.setWordWrap(True)
        layout.addWidget(instructions)

        self._target_label = QLabel("Target speed: —")
        layout.addWidget(self._target_label)

        self._speed_label = QLabel("Current speed: —")
        layout.addWidget(self._speed_label)

        self._status_label = QLabel(_PHASE_MESSAGES[SpinDownPhase.IDLE])
        self._status_label.setWordWrap(True)
        layout.addWidget(self._status_label)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        self._start_button = QPushButton("Start")
        self._start_button.clicked.connect(self._on_start_clicked)
        button_row.addWidget(self._start_button)
        self._close_button = QPushButton("Close")
        self._close_button.clicked.connect(self.reject)
        button_row.addWidget(self._close_button)
        layout.addLayout(button_row)

        self._state_received.connect(self._apply_state)
        self._controller = controller_factory(self._state_received.emit)

    def _on_start_clicked(self) -> None:
        self._start_button.setEnabled(False)
        self._speed_label.setStyleSheet(_NORMAL_STYLE)
        self._controller.start()

    @Slot(object)
    def _apply_state(self, state: SpinDownState) -> None:
        if state.target_low_kmh is not None and state.target_high_kmh is not None:
            self._target_low_kmh = state.target_low_kmh
            self._target_high_kmh = state.target_high_kmh
            self._target_label.setText(
                f"Target speed: {state.target_low_kmh:.1f} – {state.target_high_kmh:.1f} km/h"
            )

        self._status_label.setText(state.message or _PHASE_MESSAGES.get(state.phase, ""))

        if state.phase in (SpinDownPhase.SUCCESS, SpinDownPhase.ERROR):
            self._start_button.setEnabled(True)
            self._start_button.setText(
                "Retry" if state.phase is SpinDownPhase.ERROR else "Start"
            )

    def update_current_speed(self, speed_kmh: float) -> None:
        """Display the trainer's live speed, highlighting it when inside the target band."""
        self._speed_label.setText(f"Current speed: {speed_kmh:.1f} km/h")
        in_band = (
            self._target_low_kmh is not None
            and self._target_high_kmh is not None
            and self._target_low_kmh <= speed_kmh <= self._target_high_kmh
        )
        self._speed_label.setStyleSheet(_IN_BAND_STYLE if in_band else _NORMAL_STYLE)

    def reject(self) -> None:
        self._controller.cancel()
        super().reject()

    def closeEvent(self, event: QCloseEvent) -> None:
        self._controller.cancel()
        super().closeEvent(event)

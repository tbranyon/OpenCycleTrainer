from __future__ import annotations

from PySide6.QtWidgets import QLabel

from opencycletrainer.core.control.spin_down import SpinDownPhase, SpinDownState
from opencycletrainer.ui.spin_down_dialog import SpinDownDialog


class _FakeController:
    def __init__(self, status_callback) -> None:
        self.status_callback = status_callback
        self.started = 0
        self.cancelled = 0

    def start(self) -> None:
        self.started += 1

    def cancel(self) -> None:
        self.cancelled += 1


def _make_dialog():
    holder = {}

    def factory(status_callback):
        holder["controller"] = _FakeController(status_callback)
        return holder["controller"]

    dialog = SpinDownDialog("Wahoo KICKR", factory)
    return dialog, holder["controller"]


def _labels_text(dialog) -> str:
    return " | ".join(label.text() for label in dialog.findChildren(QLabel))


def test_dialog_title_contains_device_name(qapp):
    dialog, _ = _make_dialog()
    assert "Wahoo KICKR" in dialog.windowTitle()


def test_start_button_invokes_controller(qapp):
    dialog, controller = _make_dialog()
    dialog._start_button.click()
    assert controller.started == 1
    assert not dialog._start_button.isEnabled()


def test_dialog_shows_target_band_and_spin_up_message(qapp):
    dialog, controller = _make_dialog()
    controller.status_callback(
        SpinDownState(phase=SpinDownPhase.SPIN_UP, target_low_kmh=30.0, target_high_kmh=35.0)
    )
    text = _labels_text(dialog)
    assert "30.0" in text
    assert "35.0" in text
    assert "Increase" in text


def test_dialog_highlights_in_band_speed(qapp):
    dialog, controller = _make_dialog()
    controller.status_callback(
        SpinDownState(phase=SpinDownPhase.SPIN_UP, target_low_kmh=30.0, target_high_kmh=35.0)
    )

    dialog.update_current_speed(32.0)
    assert "32.0" in dialog._speed_label.text()
    assert dialog._speed_label.styleSheet() != ""

    dialog.update_current_speed(20.0)
    assert dialog._speed_label.styleSheet() == ""


def test_dialog_re_enables_start_on_error(qapp):
    dialog, controller = _make_dialog()
    dialog._start_button.click()
    controller.status_callback(
        SpinDownState(phase=SpinDownPhase.ERROR, message="Spin-down failed. Please retry.")
    )
    assert dialog._start_button.isEnabled()
    assert "failed" in _labels_text(dialog).lower()


def test_closing_dialog_cancels_controller(qapp):
    dialog, controller = _make_dialog()
    dialog.reject()
    assert controller.cancelled == 1

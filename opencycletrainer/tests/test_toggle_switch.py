from __future__ import annotations

import os

from PySide6.QtWidgets import QApplication, QCheckBox

from opencycletrainer.ui.toggle_switch import ToggleSwitch


def _get_or_create_qapp() -> QApplication:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_toggle_switch_is_a_checkbox():
    _get_or_create_qapp()
    toggle = ToggleSwitch("Enable feature")

    assert isinstance(toggle, QCheckBox)
    assert toggle.text() == "Enable feature"


def test_toggle_switch_reports_checked_state():
    _get_or_create_qapp()
    toggle = ToggleSwitch()

    assert not toggle.isChecked()
    toggle.setChecked(True)
    assert toggle.isChecked()


def test_toggle_switch_emits_toggled_signal():
    _get_or_create_qapp()
    toggle = ToggleSwitch()
    emitted: list[bool] = []
    toggle.toggled.connect(emitted.append)

    toggle.setChecked(True)
    toggle.setChecked(False)

    assert emitted == [True, False]


def test_toggle_switch_thumb_follows_checked_state():
    _get_or_create_qapp()
    toggle = ToggleSwitch()

    off_position = toggle._thumb_x
    toggle.setChecked(True)
    # The animation may be in flight; force it to its end value to assert intent.
    toggle._thumb_animation.setCurrentTime(toggle._thumb_animation.duration())

    assert toggle._thumb_x > off_position

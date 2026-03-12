from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("PYQTGRAPH_QT_LIB", "PySide6")

from opencycletrainer.ui.main_window import MainWindow


class _ShutdownSpy:
    """Minimal backend spy that records shutdown calls."""

    def __init__(self) -> None:
        self.shutdown_called = False

    def get_paired_devices(self) -> list:
        return []

    def get_available_devices(self) -> list:
        return []

    def shutdown(self) -> None:
        self.shutdown_called = True


def test_main_window_close_event_shuts_down_backend(qapp):
    window = MainWindow()
    spy = _ShutdownSpy()
    window.devices_screen._backend = spy

    window.close()

    assert spy.shutdown_called

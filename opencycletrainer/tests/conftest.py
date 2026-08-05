from __future__ import annotations

import os

# Must be set before any Qt or pyqtgraph module is imported.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("PYQTGRAPH_QT_LIB", "PySide6")

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


# Tests drive process_tick() explicitly from an injected fake monotonic clock,
# but the controller's real tick timer keeps running against the real clock, and
# one-second recorder bins are keyed on real UTC time. An unscheduled tick landing
# between two test steps therefore opens a bin the test never asked for. Stretching
# the interval keeps the timer object and its isActive() semantics (which the
# trainer-connection wiring reads) intact while guaranteeing it never fires within
# a test; no test relies on the tick arriving on its own.
_INERT_TICK_INTERVAL_MS = 24 * 60 * 60 * 1000


@pytest.fixture(autouse=True)
def shutdown_workout_controllers(monkeypatch):
    """Keep workout controller tick timers from firing into unrelated tests.

    Each controller is stretched to an inert tick interval on construction and
    shut down at teardown. Tests shut their controllers down explicitly, but a
    failed assertion skips that trailing call, and the orphaned QTimer then ticks
    on into later tests. Tracking every instance makes the teardown
    unconditional; shutdown() is idempotent, so controllers already stopped by
    the test are unaffected.
    """
    from shiboken6 import isValid  # noqa: PLC0415

    from opencycletrainer.ui.workout_controller import WorkoutSessionController  # noqa: PLC0415

    controllers: list[WorkoutSessionController] = []
    original_init = WorkoutSessionController.__init__

    def _tracking_init(self, *args, **kwargs) -> None:
        original_init(self, *args, **kwargs)
        self._timer.setInterval(_INERT_TICK_INTERVAL_MS)
        controllers.append(self)

    monkeypatch.setattr(WorkoutSessionController, "__init__", _tracking_init)
    yield
    for controller in controllers:
        # A controller parented to a closed window is already torn down, and its
        # C++ half is gone — touching its timer from here would raise.
        if isValid(controller):
            controller.shutdown()

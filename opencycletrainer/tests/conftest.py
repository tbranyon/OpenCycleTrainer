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


# Hotkeys detached from the application, kept so their screens are never freed.
_DETACHED_HOTKEYS: list = []


@pytest.fixture(autouse=True)
def detach_workout_hotkeys(monkeypatch):
    """Remove each test's application-wide hotkey filters at teardown.

    WorkoutHotkeys installs itself as an event filter on the QApplication and only
    removes itself when its screen is destroyed. Tests never destroy their screens,
    so every filter stays installed and runs on every later event: per-test cost
    grows linearly with the number of earlier Qt tests, and late in the run a single
    test takes seconds. Detached hotkeys are kept referenced for the session so
    their screens stay alive exactly as before; letting the garbage collector free
    them mid-session crashes Qt while recorder writer threads are still running.
    """
    from shiboken6 import isValid  # noqa: PLC0415

    from opencycletrainer.ui.hotkeys import WorkoutHotkeys  # noqa: PLC0415

    instances: list[WorkoutHotkeys] = []
    original_init = WorkoutHotkeys.__init__

    def _tracking_init(self, *args, **kwargs) -> None:
        original_init(self, *args, **kwargs)
        instances.append(self)

    monkeypatch.setattr(WorkoutHotkeys, "__init__", _tracking_init)
    yield
    app = QApplication.instance()
    for hotkeys in instances:
        # Hotkeys of a screen the test already closed are gone with it.
        if app is not None and isValid(hotkeys):
            app.removeEventFilter(hotkeys)
    _DETACHED_HOTKEYS.extend(instances)


@pytest.fixture(autouse=True)
def shutdown_workout_controllers(monkeypatch, detach_workout_hotkeys):
    """Keep workout controller tick timers from firing into unrelated tests.

    Each controller is stretched to an inert tick interval on construction and
    shut down at teardown. Tests shut their controllers down explicitly, but a
    failed assertion skips that trailing call, and the orphaned QTimer then ticks
    on into later tests. Tracking every instance makes the teardown
    unconditional; shutdown() is idempotent, so controllers already stopped by
    the test are unaffected. Depends on detach_workout_hotkeys so controllers
    shut down before their hotkeys are detached.
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

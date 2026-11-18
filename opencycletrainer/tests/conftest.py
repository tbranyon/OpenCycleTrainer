from __future__ import annotations

import os

# Must be set before any Qt or pyqtgraph module is imported.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("PYQTGRAPH_QT_LIB", "PySide6")

import gc

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication

# One application for the whole run, held here until the interpreter exits. Many test
# modules create it from a helper and drop the only Python reference; with nothing
# holding it, widgets still alive at interpreter exit crash Qt during teardown.
_APP = QApplication.instance() or QApplication([])


@pytest.fixture(scope="session")
def qapp():
    return _APP


@pytest.fixture(scope="session", autouse=True)
def tear_down_qt_at_session_end():
    """Destroy leftover windows on the main thread before the interpreter shuts down.

    Otherwise they are freed during interpreter teardown, after parts of Qt are gone,
    and the process segfaults even though every test passed.
    """
    yield
    for widget in QApplication.topLevelWidgets():
        widget.close()
        widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    gc.collect()


@pytest.fixture(autouse=True)
def discard_unfinished_recordings(monkeypatch):
    """Discard any recording a test leaves running, so its writer thread stops.

    A recorder's writer thread lives until its session ends. Left running, it can
    trigger garbage collection of Qt objects off the GUI thread, which crashes Qt,
    and it is still alive when the interpreter exits.
    """
    from opencycletrainer.core.recorder import WorkoutRecorder  # noqa: PLC0415

    recorders: list[WorkoutRecorder] = []
    original_init = WorkoutRecorder.__init__

    def _tracking_init(self, *args, **kwargs) -> None:
        original_init(self, *args, **kwargs)
        recorders.append(self)

    monkeypatch.setattr(WorkoutRecorder, "__init__", _tracking_init)
    yield
    for recorder in recorders:
        recorder.discard()


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
def shutdown_workout_controllers(monkeypatch, detach_workout_hotkeys, discard_unfinished_recordings):
    """Keep workout controller tick timers from firing into unrelated tests.

    Each controller is stretched to an inert tick interval on construction and
    shut down at teardown. Tests shut their controllers down explicitly, but a
    failed assertion skips that trailing call, and the orphaned QTimer then ticks
    on into later tests. Tracking every instance makes the teardown
    unconditional; shutdown() is idempotent, so controllers already stopped by
    the test are unaffected. Depends on detach_workout_hotkeys so controllers
    shut down before their hotkeys are detached, and on discard_unfinished_recordings
    so controllers finish their own recordings before leftovers are discarded.
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


class _OfflineTileProvider:
    """Stands in for the map's network tile provider so no test downloads real map tiles."""

    def __init__(self) -> None:
        from PySide6.QtCore import QObject, Signal  # noqa: PLC0415

        from opencycletrainer.ui.map_tiles import OPENSTREETMAP  # noqa: PLC0415

        class _Signals(QObject):
            tile_ready = Signal(int, int, int)

        self._signals = _Signals()
        self.tile_ready = self._signals.tile_ready
        self.source = OPENSTREETMAP

    def set_wanted(self, tiles) -> None:  # noqa: ARG002
        return None

    def image(self, key):  # noqa: ARG002
        return None


@pytest.fixture(autouse=True)
def offline_map_tiles(monkeypatch):
    """Keep every map created by a test off the network."""
    from opencycletrainer.ui import map_tiles  # noqa: PLC0415

    monkeypatch.setattr(map_tiles, "create_default_tile_provider", _OfflineTileProvider)

from __future__ import annotations

import os

# Must be set before any Qt or pyqtgraph module is imported.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("PYQTGRAPH_QT_LIB", "PySide6")

from collections import Counter
import sys

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication

# One application for the whole run. Many test modules create it from a helper and
# drop the only Python reference; held here, it outlives every widget a test creates.
_APP = QApplication.instance() or QApplication([])


@pytest.fixture(scope="session")
def qapp():
    return _APP


_session: pytest.Session | None = None


def pytest_sessionstart(session: pytest.Session) -> None:
    global _session  # noqa: PLW0603
    _session = session


def pytest_terminal_summary(terminalreporter) -> None:
    """List the windows tests left alive, by type, so leaks are visible as they are fixed."""
    from shiboken6 import isValid  # noqa: PLC0415

    leftovers = Counter(
        type(widget).__name__ for widget in QApplication.topLevelWidgets() if isValid(widget)
    )
    if not leftovers:
        return
    terminalreporter.section("Qt windows still alive at the end of the run")
    for name, count in sorted(leftovers.items(), key=lambda item: (-item[1], item[0])):
        terminalreporter.write_line(f"{count:6d}  {name}")
    terminalreporter.write_line(f"{sum(leftovers.values()):6d}  total")


@pytest.hookimpl(trylast=True)
def pytest_unconfigure(config: pytest.Config) -> None:  # noqa: ARG001
    """End the process once pytest has finished, skipping interpreter teardown.

    Some tests still leave windows alive (listed in the run's summary), and pyqtgraph
    plots among them cannot be destroyed safely in bulk: freeing them during interpreter
    teardown, or deleting their windows from C++, segfaults the process after every test
    has passed. Results are already reported and written by now.
    """
    exit_status = int(_session.exitstatus) if _session is not None else 0
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(exit_status)


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


@pytest.fixture(autouse=True)
def detach_workout_hotkeys(monkeypatch):
    """Remove each test's application-wide hotkey filters at teardown.

    WorkoutHotkeys installs itself as an event filter on the QApplication and only
    removes itself when its screen is destroyed. A screen a test leaves alive (one
    inside a main window the test never closed, say) would keep its filter installed,
    running on every later event: per-test cost would grow with every earlier Qt test.
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


@pytest.fixture(autouse=True)
def dispose_workout_screens(monkeypatch):
    """Delete the workout screens each test creates, once the test is over.

    Each screen holds the charts and the course map, whose pyqtgraph plots crash Qt if
    they are left for the garbage collector or freed in bulk at the end of the run.
    Screens inside a parent (a main window) go with their parent instead.
    """
    from shiboken6 import isValid  # noqa: PLC0415

    from opencycletrainer.ui.workout_screen import WorkoutScreen  # noqa: PLC0415

    screens: list[WorkoutScreen] = []
    original_init = WorkoutScreen.__init__

    def _tracking_init(self, *args, **kwargs) -> None:
        original_init(self, *args, **kwargs)
        screens.append(self)

    monkeypatch.setattr(WorkoutScreen, "__init__", _tracking_init)
    yield
    for screen in screens:
        if isValid(screen) and screen.parent() is None:
            screen.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


@pytest.fixture(autouse=True)
def shutdown_workout_controllers(
    monkeypatch, detach_workout_hotkeys, discard_unfinished_recordings, dispose_workout_screens
):
    """Keep workout controller tick timers from firing into unrelated tests.

    Each controller is stretched to an inert tick interval on construction and
    shut down at teardown. Tests shut their controllers down explicitly, but a
    failed assertion skips that trailing call, and the orphaned QTimer then ticks
    on into later tests. Tracking every instance makes the teardown
    unconditional; shutdown() is idempotent, so controllers already stopped by
    the test are unaffected. Depends on detach_workout_hotkeys so controllers
    shut down before their hotkeys are detached, on discard_unfinished_recordings
    so controllers finish their own recordings before leftovers are discarded, and
    on dispose_workout_screens so controllers stop before their screens are deleted.
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

    def __init__(self, source) -> None:
        from PySide6.QtCore import QObject, Signal  # noqa: PLC0415

        class _Signals(QObject):
            tile_ready = Signal(int, int, int)

        self._signals = _Signals()
        self.tile_ready = self._signals.tile_ready
        self.source = source

    def set_wanted(self, tiles) -> None:  # noqa: ARG002
        return None

    def image(self, key):  # noqa: ARG002
        return None


@pytest.fixture(autouse=True)
def offline_map_tiles(monkeypatch):
    """Keep every map created by a test off the network."""
    from opencycletrainer.ui import map_tiles  # noqa: PLC0415

    monkeypatch.setattr(map_tiles, "create_tile_provider", _OfflineTileProvider)

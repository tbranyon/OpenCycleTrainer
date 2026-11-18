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


def _track_instances(monkeypatch, cls, on_create=None) -> list:
    """Return a list that collects every *cls* created during the current test.

    *on_create*, if given, is called with each new instance.
    """
    instances: list = []
    original_init = cls.__init__

    def _tracking_init(self, *args, **kwargs) -> None:
        original_init(self, *args, **kwargs)
        if on_create is not None:
            on_create(self)
        instances.append(self)

    monkeypatch.setattr(cls, "__init__", _tracking_init)
    return instances


_HELPER_WINDOW_MODULES = ("PySide6", "pyqtgraph")


def _delete_windows(windows) -> None:
    """Delete the windows not already gone, except those a parent will take with it.

    Each pyqtgraph plot keeps parentless helper windows (its right-click menus and
    options panel) that it touches when it is destroyed, so deleting a helper before
    the plot's window crashes Qt. The app's windows and pyqtgraph canvases go first;
    plain Qt and pyqtgraph windows still left afterwards go next.
    """
    from PySide6.QtWidgets import QGraphicsView  # noqa: PLC0415
    from shiboken6 import isValid  # noqa: PLC0415

    def _is_helper(window) -> bool:
        return (
            type(window).__module__.startswith(_HELPER_WINDOW_MODULES)
            and not isinstance(window, QGraphicsView)
        )

    remaining = list(windows)
    for delete_helpers in (False, True):
        for window in remaining:
            if (
                isValid(window)
                and window.parent() is None
                and _is_helper(window) == delete_helpers
            ):
                window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


@pytest.fixture(autouse=True)
def discard_unfinished_recordings(monkeypatch):
    """Discard any recording a test leaves running, so its writer thread stops.

    A recorder's writer thread lives until its session ends. Left running, it can
    trigger garbage collection of Qt objects off the GUI thread, which crashes Qt,
    and it is still alive when the interpreter exits.
    """
    from opencycletrainer.core.recorder import WorkoutRecorder  # noqa: PLC0415

    recorders = _track_instances(monkeypatch, WorkoutRecorder)
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
    removes itself when its screen is destroyed. A screen a test leaves alive would
    keep its filter installed, running on every later event: per-test cost would
    grow with every earlier Qt test.
    """
    from shiboken6 import isValid  # noqa: PLC0415

    from opencycletrainer.ui.hotkeys import WorkoutHotkeys  # noqa: PLC0415

    instances = _track_instances(monkeypatch, WorkoutHotkeys)
    yield
    app = QApplication.instance()
    for hotkeys in instances:
        # Hotkeys of a screen the test already closed are gone with it.
        if app is not None and isValid(hotkeys):
            app.removeEventFilter(hotkeys)


@pytest.fixture(autouse=True)
def dispose_new_windows():
    """Delete every window a test leaves behind, once the test is over.

    That is any widget without a parent that appeared during the test: screens,
    dialogs, charts and maps a test built on their own, and the right-click menus
    pyqtgraph creates for each plot, which outlive the plot. Left alive, pyqtgraph plots
    crash Qt when the garbage collector frees them, or when freed in bulk at the end of
    the run. Widgets inside a parent go with their parent.
    """
    from shiboken6 import isValid  # noqa: PLC0415

    existing = {id(widget) for widget in QApplication.topLevelWidgets() if isValid(widget)}
    yield
    _delete_windows(
        widget
        for widget in QApplication.topLevelWidgets()
        if isValid(widget) and id(widget) not in existing
    )


@pytest.fixture(autouse=True)
def close_main_windows(monkeypatch, dispose_new_windows):
    """Close the main windows each test creates, once the test is over.

    Closing runs the window's own shutdown (sync, controller, device backend), which is
    safe to repeat for windows the test already closed. Depends on dispose_new_windows
    so each window is closed before it is deleted.
    """
    from shiboken6 import isValid  # noqa: PLC0415

    from opencycletrainer.ui.main_window import MainWindow  # noqa: PLC0415

    windows = _track_instances(monkeypatch, MainWindow)
    yield
    for window in windows:
        if isValid(window):
            window.close()


@pytest.fixture(autouse=True)
def shutdown_workout_controllers(
    monkeypatch,
    detach_workout_hotkeys,
    discard_unfinished_recordings,
    dispose_new_windows,
    close_main_windows,
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
    on the window fixtures so controllers stop before their screens are deleted.
    """
    from shiboken6 import isValid  # noqa: PLC0415

    from opencycletrainer.ui.workout_controller import WorkoutSessionController  # noqa: PLC0415

    controllers = _track_instances(
        monkeypatch,
        WorkoutSessionController,
        on_create=lambda controller: controller._timer.setInterval(_INERT_TICK_INTERVAL_MS),
    )
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

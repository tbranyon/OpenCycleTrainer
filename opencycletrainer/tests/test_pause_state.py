from __future__ import annotations

import pytest

from opencycletrainer.ui.pause_state import PauseState


# ── Fake dialog ───────────────────────────────────────────────────────────────

class _FakeSignal:
    """Minimal Qt-signal stand-in: supports .connect() and .emit()."""

    def __init__(self) -> None:
        self._callbacks: list = []

    def connect(self, fn) -> None:
        self._callbacks.append(fn)

    def emit(self) -> None:
        for cb in self._callbacks:
            cb()


class _FakePauseDialog:
    """Minimal PauseDialog substitute that avoids Qt in unit tests."""

    def __init__(self, parent=None) -> None:
        self.resume_started = _FakeSignal()
        self._visible = False

    def show(self) -> None:
        self._visible = True

    def close(self) -> None:
        self._visible = False

    def isVisible(self) -> bool:
        return self._visible


def _make_pause_state(resume_callback=None) -> PauseState:
    """Build a PauseState with a fake dialog factory and optional callback."""
    if resume_callback is None:
        resume_callback = lambda: None  # noqa: E731
    return PauseState(
        screen=object(),
        resume_callback=resume_callback,
        _dialog_factory=_FakePauseDialog,
    )


# ── Defaults ──────────────────────────────────────────────────────────────────


class TestPauseStateDefaults:
    def test_pause_dialog_is_none(self):
        ps = _make_pause_state()
        assert ps.pause_dialog is None

    def test_pause_start_monotonic_is_none(self):
        ps = _make_pause_state()
        assert ps.pause_start_monotonic is None

    def test_total_paused_duration_is_zero(self):
        ps = _make_pause_state()
        assert ps.total_paused_duration == pytest.approx(0.0)


# ── pause() ───────────────────────────────────────────────────────────────────


class TestPause:
    def test_pause_sets_pause_start_monotonic(self):
        ps = _make_pause_state()
        ps.pause(10.0)
        assert ps.pause_start_monotonic == pytest.approx(10.0)

    def test_pause_creates_dialog(self):
        ps = _make_pause_state()
        ps.pause(0.0)
        assert ps.pause_dialog is not None

    def test_pause_shows_dialog(self):
        ps = _make_pause_state()
        ps.pause(0.0)
        assert ps.pause_dialog.isVisible()

    def test_pause_connects_resume_callback(self):
        called: list[bool] = []
        ps = _make_pause_state(resume_callback=lambda: called.append(True))
        ps.pause(0.0)
        ps.pause_dialog.resume_started.emit()
        assert called == [True]


# ── on_ramp_in_to_running() ───────────────────────────────────────────────────


class TestOnRampInToRunning:
    def test_accumulates_paused_duration(self):
        ps = _make_pause_state()
        ps.pause(5.0)  # pause started at t=5
        ps.on_ramp_in_to_running(8.0)  # 3 seconds of pause accumulated
        assert ps.total_paused_duration == pytest.approx(3.0)

    def test_clears_pause_start_monotonic(self):
        ps = _make_pause_state()
        ps.pause(5.0)
        ps.on_ramp_in_to_running(8.0)
        assert ps.pause_start_monotonic is None

    def test_noop_when_not_paused(self):
        ps = _make_pause_state()
        ps.on_ramp_in_to_running(10.0)  # no active pause — must not raise
        assert ps.total_paused_duration == pytest.approx(0.0)
        assert ps.pause_start_monotonic is None

    def test_multiple_cycles_accumulate(self):
        ps = _make_pause_state()
        # First pause: 3 s
        ps.pause(5.0)
        ps.on_ramp_in_to_running(8.0)
        # Second pause: 2 s
        ps.pause(20.0)
        ps.on_ramp_in_to_running(22.0)
        assert ps.total_paused_duration == pytest.approx(5.0)


# ── total_paused_plus_current() ───────────────────────────────────────────────


class TestTotalPausedPlusCurrent:
    def test_returns_zero_when_not_paused(self):
        ps = _make_pause_state()
        assert ps.total_paused_plus_current(100.0) == pytest.approx(0.0)

    def test_returns_running_pause_duration_while_paused(self):
        ps = _make_pause_state()
        ps.pause(10.0)
        result = ps.total_paused_plus_current(15.0)
        assert result == pytest.approx(5.0)

    def test_includes_previously_accumulated_and_current(self):
        ps = _make_pause_state()
        # First pause: 3 s accumulated
        ps.pause(5.0)
        ps.on_ramp_in_to_running(8.0)
        # Second pause in progress: 2 s so far
        ps.pause(20.0)
        result = ps.total_paused_plus_current(22.0)
        assert result == pytest.approx(5.0)

    def test_returns_only_accumulated_after_resume(self):
        ps = _make_pause_state()
        ps.pause(5.0)
        ps.on_ramp_in_to_running(8.0)  # 3 s accumulated, now running
        result = ps.total_paused_plus_current(100.0)
        assert result == pytest.approx(3.0)


# ── close_dialog() ────────────────────────────────────────────────────────────


class TestCloseDialog:
    def test_closes_and_nils_dialog(self):
        ps = _make_pause_state()
        ps.pause(0.0)
        assert ps.pause_dialog is not None
        ps.close_dialog()
        assert ps.pause_dialog is None

    def test_noop_when_no_dialog(self):
        ps = _make_pause_state()
        ps.close_dialog()  # must not raise
        assert ps.pause_dialog is None


# ── reset() ───────────────────────────────────────────────────────────────────


class TestReset:
    def test_clears_pause_start_monotonic(self):
        ps = _make_pause_state()
        ps.pause(5.0)
        ps.reset()
        assert ps.pause_start_monotonic is None

    def test_clears_total_paused_duration(self):
        ps = _make_pause_state()
        ps.pause(5.0)
        ps.on_ramp_in_to_running(8.0)
        ps.reset()
        assert ps.total_paused_duration == pytest.approx(0.0)

    def test_reset_while_actively_paused(self):
        ps = _make_pause_state()
        ps.pause(5.0)
        ps.reset()
        assert ps.pause_start_monotonic is None
        assert ps.total_paused_duration == pytest.approx(0.0)

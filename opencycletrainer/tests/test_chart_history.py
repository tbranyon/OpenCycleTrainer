from __future__ import annotations

import pytest

from opencycletrainer.ui.chart_history import ChartHistory


# ── Fakes ─────────────────────────────────────────────────────────────────────


class _FakeTimer:
    """Minimal QTimer substitute: tracks active state and last interval."""

    def __init__(self) -> None:
        self._active = False
        self._interval = 0

    def setInterval(self, ms: int) -> None:
        self._interval = ms

    def start(self) -> None:
        self._active = True

    def stop(self) -> None:
        self._active = False

    def isActive(self) -> bool:
        return self._active


class _FakePowerHistory:
    def __init__(self, series: list[tuple[float, int]] | None = None) -> None:
        self._series = series or []

    def as_series(self) -> list[tuple[float, int]]:
        return list(self._series)


class _FakePauseState:
    def __init__(self, paused: float = 0.0) -> None:
        self._paused = paused

    def total_paused_plus_current(self, now: float) -> float:  # noqa: ARG002
        return self._paused


class _FakeScreen:
    def __init__(self) -> None:
        self.chart_calls: list[dict] = []
        self.free_ride_calls: list[dict] = []

    def update_charts(
        self,
        elapsed: float,
        interval_index,
        power_series: list,
        hr_series: list,
    ) -> None:
        self.chart_calls.append(
            {
                "elapsed": elapsed,
                "interval_index": interval_index,
                "power_series": power_series,
                "hr_series": hr_series,
            }
        )

    def update_free_ride_charts(
        self,
        elapsed: float,
        power_series: list,
        hr_series: list,
    ) -> None:
        self.free_ride_calls.append(
            {
                "elapsed": elapsed,
                "power_series": power_series,
                "hr_series": hr_series,
            }
        )


def _make(
    *,
    power_series: list[tuple[float, int]] | None = None,
    paused: float = 0.0,
    clock_fn=None,
) -> tuple[ChartHistory, _FakeTimer, _FakeScreen, _FakePauseState]:
    timer = _FakeTimer()
    screen = _FakeScreen()
    power_history = _FakePowerHistory(power_series)
    pause_state = _FakePauseState(paused)
    clock = clock_fn if clock_fn is not None else (lambda: 0.0)
    ch = ChartHistory(
        screen,
        clock,
        power_history,
        pause_state,
        _timer_factory=lambda: timer,
    )
    return ch, timer, screen, pause_state


# ── Defaults ──────────────────────────────────────────────────────────────────


class TestDefaults:
    def test_chart_start_monotonic_is_none(self):
        ch, *_ = _make()
        assert ch.chart_start_monotonic is None

    def test_hr_history_is_empty(self):
        ch, *_ = _make()
        assert ch.hr_history == []

    def test_skip_events_is_empty(self):
        ch, *_ = _make()
        assert ch.skip_events == []

    def test_timer_not_active(self):
        ch, timer, *_ = _make()
        assert not timer.isActive()

    def test_timer_interval_set_to_1000ms(self):
        ch, timer, *_ = _make()
        assert timer._interval == 1000

    def test_chart_timer_property_returns_timer(self):
        ch, timer, *_ = _make()
        assert ch.chart_timer is timer


# ── start() ───────────────────────────────────────────────────────────────────


class TestStart:
    def test_sets_chart_start_monotonic(self):
        ch, *_ = _make()
        ch.start(42.0)
        assert ch.chart_start_monotonic == pytest.approx(42.0)

    def test_starts_timer(self):
        ch, timer, *_ = _make()
        ch.start(0.0)
        assert timer.isActive()

    def test_zero_start(self):
        ch, *_ = _make()
        ch.start(0.0)
        assert ch.chart_start_monotonic == pytest.approx(0.0)


# ── stop() ────────────────────────────────────────────────────────────────────


class TestStop:
    def test_stops_timer(self):
        ch, timer, *_ = _make()
        ch.start(0.0)
        ch.stop()
        assert not timer.isActive()

    def test_stop_when_not_started_is_noop(self):
        ch, timer, *_ = _make()
        ch.stop()
        assert not timer.isActive()


# ── reset() ───────────────────────────────────────────────────────────────────


class TestReset:
    def test_clears_chart_start_monotonic(self):
        ch, *_ = _make()
        ch.start(10.0)
        ch.reset()
        assert ch.chart_start_monotonic is None

    def test_clears_hr_history(self):
        now_val = [0.0]
        ch, *_ = _make(clock_fn=lambda: now_val[0])
        ch.start(0.0)
        now_val[0] = 1.0
        ch.record_hr(140, 1.0)
        ch.reset()
        assert ch.hr_history == []

    def test_clears_skip_events(self):
        ch, *_ = _make()
        ch.start(0.0)
        ch.record_skip(5.0, 10.0, 15.0)
        ch.reset()
        assert ch.skip_events == []

    def test_does_not_stop_timer(self):
        """reset() clears data state but does not touch the timer."""
        ch, timer, *_ = _make()
        ch.start(0.0)
        ch.reset()
        # Timer state is managed independently by start()/stop()
        assert timer.isActive()


# ── record_hr() ───────────────────────────────────────────────────────────────


class TestRecordHr:
    def test_appends_sample_when_started(self):
        ch, *_ = _make()
        ch.start(0.0)
        ch.record_hr(130, 1.0)
        assert ch.hr_history == [(1.0, 130)]

    def test_appends_multiple_samples(self):
        ch, *_ = _make()
        ch.start(0.0)
        ch.record_hr(130, 1.0)
        ch.record_hr(140, 2.0)
        assert len(ch.hr_history) == 2
        assert ch.hr_history[1] == (2.0, 140)

    def test_noop_before_start(self):
        ch, *_ = _make()
        ch.record_hr(120, 0.5)
        assert ch.hr_history == []

    def test_noop_after_reset(self):
        ch, *_ = _make()
        ch.start(0.0)
        ch.reset()
        ch.record_hr(120, 1.0)
        assert ch.hr_history == []

    def test_bpm_stored_as_int(self):
        ch, *_ = _make()
        ch.start(0.0)
        ch.record_hr(130, 1.0)
        _, bpm = ch.hr_history[0]
        assert isinstance(bpm, int)


# ── record_skip() ─────────────────────────────────────────────────────────────


class TestRecordSkip:
    def test_appends_skip_event(self):
        ch, *_ = _make()
        ch.start(0.0)
        ch.record_skip(5.0, 10.0, 20.0)
        assert ch.skip_events == [(5.0, 10.0, 20.0)]

    def test_multiple_skips(self):
        ch, *_ = _make()
        ch.start(0.0)
        ch.record_skip(5.0, 10.0, 20.0)
        ch.record_skip(25.0, 30.0, 45.0)
        assert len(ch.skip_events) == 2


# ── on_tick() — general ───────────────────────────────────────────────────────


class _FakeSnapshot:
    def __init__(self, interval_index=None) -> None:
        self.current_interval_index = interval_index


class TestOnTickGuard:
    def test_noop_before_start(self):
        ch, _, screen, _ = _make()
        ch.on_tick(None, None, False)
        assert screen.chart_calls == []
        assert screen.free_ride_calls == []

    def test_noop_after_reset(self):
        ch, _, screen, _ = _make()
        ch.start(0.0)
        ch.reset()
        ch.on_tick(None, None, False)
        assert screen.chart_calls == []


class TestOnTickElapsed:
    def test_elapsed_equals_clock_minus_start(self):
        now_val = [5.0]
        ch, _, screen, _ = _make(clock_fn=lambda: now_val[0])
        ch.start(0.0)
        ch.on_tick(_FakeSnapshot(), None, False)
        assert screen.chart_calls[-1]["elapsed"] == pytest.approx(5.0)

    def test_elapsed_accounts_for_paused_time(self):
        now_val = [10.0]
        ch, _, screen, _ = _make(clock_fn=lambda: now_val[0], paused=3.0)
        ch.start(0.0)
        ch.on_tick(_FakeSnapshot(), None, False)
        # 10 - 0 - 3 paused = 7
        assert screen.chart_calls[-1]["elapsed"] == pytest.approx(7.0)

    def test_elapsed_accounts_for_skip_offset(self):
        now_val = [10.0]
        ch, _, screen, _ = _make(clock_fn=lambda: now_val[0])
        ch.start(0.0)
        ch.record_skip(5.0, 10.0, 20.0)  # 10 s skipped
        ch.on_tick(_FakeSnapshot(), None, False)
        # 10 - 0 + 10 skipped = 20
        assert screen.chart_calls[-1]["elapsed"] == pytest.approx(20.0)

    def test_elapsed_accounts_for_both_skip_and_pause(self):
        now_val = [10.0]
        ch, _, screen, _ = _make(clock_fn=lambda: now_val[0], paused=2.0)
        ch.start(0.0)
        ch.record_skip(5.0, 5.0, 10.0)  # 5 s skipped
        ch.on_tick(_FakeSnapshot(), None, False)
        # 10 - 0 + 5 - 2 = 13
        assert screen.chart_calls[-1]["elapsed"] == pytest.approx(13.0)


class TestOnTickRoutingToScreen:
    def test_regular_workout_calls_update_charts(self):
        now_val = [5.0]
        ch, _, screen, _ = _make(clock_fn=lambda: now_val[0])
        ch.start(0.0)
        ch.on_tick(_FakeSnapshot(interval_index=2), None, is_free_ride=False)
        assert len(screen.chart_calls) == 1
        assert screen.free_ride_calls == []

    def test_free_ride_calls_update_free_ride_charts(self):
        now_val = [5.0]
        ch, _, screen, _ = _make(clock_fn=lambda: now_val[0])
        ch.start(0.0)
        ch.on_tick(_FakeSnapshot(), None, is_free_ride=True)
        assert len(screen.free_ride_calls) == 1
        assert screen.chart_calls == []

    def test_interval_index_passed_to_update_charts(self):
        now_val = [5.0]
        ch, _, screen, _ = _make(clock_fn=lambda: now_val[0])
        ch.start(0.0)
        ch.on_tick(_FakeSnapshot(interval_index=3), None, is_free_ride=False)
        assert screen.chart_calls[-1]["interval_index"] == 3

    def test_none_snapshot_passes_none_interval_index(self):
        now_val = [5.0]
        ch, _, screen, _ = _make(clock_fn=lambda: now_val[0])
        ch.start(0.0)
        ch.on_tick(None, None, is_free_ride=False)
        assert screen.chart_calls[-1]["interval_index"] is None


class TestOnTickPowerSeries:
    def test_power_series_mapped_to_elapsed_time(self):
        """Power samples at monotonic t=1,2 from start=0 → elapsed 1.0, 2.0."""
        now_val = [5.0]
        ch, _, screen, _ = _make(
            clock_fn=lambda: now_val[0],
            power_series=[(1.0, 200), (2.0, 210)],
        )
        ch.start(0.0)
        ch.on_tick(_FakeSnapshot(), None, False)
        ps = screen.chart_calls[-1]["power_series"]
        assert len(ps) == 2
        assert ps[0] == pytest.approx((1.0, 200))
        assert ps[1] == pytest.approx((2.0, 210))

    def test_power_series_adjusted_after_skip(self):
        """Samples taken after a skip should be shifted by the skipped duration."""
        now_val = [20.0]
        # Skip at mono=5: elapsed 10→15 (5 s jump)
        ch, _, screen, _ = _make(
            clock_fn=lambda: now_val[0],
            power_series=[(3.0, 200), (8.0, 210)],  # sample at 3 before skip, 8 after
        )
        ch.start(0.0)
        ch.record_skip(5.0, 10.0, 15.0)  # skip at mono=5, +5s offset
        ch.on_tick(_FakeSnapshot(), None, False)
        ps = screen.chart_calls[-1]["power_series"]
        # sample at mono=3: before skip (skip_mono=5 > 3), no offset → 3 - 0 = 3.0
        assert ps[0][0] == pytest.approx(3.0)
        # sample at mono=8: after skip (skip_mono=5 <= 8), +5 → 8 - 0 + 5 = 13.0
        assert ps[1][0] == pytest.approx(13.0)


class TestOnTickHrSeries:
    def test_hr_series_mapped_to_elapsed_time(self):
        now_val = [5.0]
        ch, _, screen, _ = _make(clock_fn=lambda: now_val[0])
        ch.start(0.0)
        ch.record_hr(130, 1.0)
        ch.record_hr(140, 3.0)
        ch.on_tick(_FakeSnapshot(), None, False)
        hs = screen.chart_calls[-1]["hr_series"]
        assert len(hs) == 2
        assert hs[0] == pytest.approx((1.0, 130))
        assert hs[1] == pytest.approx((3.0, 140))

    def test_empty_hr_series_when_no_hr_received(self):
        now_val = [5.0]
        ch, _, screen, _ = _make(clock_fn=lambda: now_val[0])
        ch.start(0.0)
        ch.on_tick(_FakeSnapshot(), None, False)
        assert screen.chart_calls[-1]["hr_series"] == []

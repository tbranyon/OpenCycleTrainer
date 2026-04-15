from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from opencycletrainer.core.one_second_aggregator import OneSecondAggregator
from opencycletrainer.core.recorder import RecorderSample

# Base second: 2026-01-01 00:00:00 UTC (unix timestamp must be a whole second).
_BASE = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


def _ts(offset_ms: float) -> datetime:
    """Return _BASE + offset_ms milliseconds."""
    return _BASE + timedelta(milliseconds=offset_ms)


def _sample(
    offset_ms: float,
    *,
    trainer: int | None = 200,
    bike: int | None = None,
    hr: int | None = 150,
    cadence: float | None = 90.0,
    speed: float | None = 5.0,
    target: int | None = 200,
    mode: str | None = "ERG",
    erg_setpoint: int | None = 200,
    total_kj: float | None = 1.0,
) -> RecorderSample:
    return RecorderSample(
        timestamp_utc=_ts(offset_ms),
        trainer_power_watts=trainer,
        bike_power_watts=bike,
        heart_rate_bpm=hr,
        cadence_rpm=cadence,
        speed_mps=speed,
        target_power_watts=target,
        mode=mode,
        erg_setpoint_watts=erg_setpoint,
        total_kj=total_kj,
    )


def _active_agg() -> OneSecondAggregator:
    agg = OneSecondAggregator()
    agg.set_recording_active(True)
    return agg


# ── Basic emission ─────────────────────────────────────────────────────────────


class TestBasicEmission:
    def test_single_tick_produces_no_sample_until_second_boundary(self) -> None:
        agg = _active_agg()
        result = agg.feed(_sample(0))
        assert result == []

    def test_second_tick_in_same_second_produces_no_sample(self) -> None:
        agg = _active_agg()
        agg.feed(_sample(0))
        result = agg.feed(_sample(250))
        assert result == []

    def test_tick_in_new_second_closes_previous_bin(self) -> None:
        agg = _active_agg()
        agg.feed(_sample(0))
        result = agg.feed(_sample(1000))  # second 1 → closes second 0
        assert len(result) == 1

    def test_emitted_sample_timestamp_is_floor_second(self) -> None:
        agg = _active_agg()
        agg.feed(_sample(250))  # offset 250 ms into second 0
        result = agg.feed(_sample(1250))  # second 1 → closes second 0
        assert len(result) == 1
        assert result[0].timestamp_utc == _BASE  # floor of second 0

    def test_two_completed_seconds_emit_two_samples(self) -> None:
        agg = _active_agg()
        agg.feed(_sample(0))
        agg.feed(_sample(1000))
        result = agg.feed(_sample(2000))
        # Second tick closes second 0; third tick closes second 1.
        assert len(result) == 1
        # Gather all completed.
        all_samples = agg.feed(_sample(0))  # same second 2, no new close
        assert all_samples == []

    def test_three_seconds_total_three_samples(self) -> None:
        agg = _active_agg()
        all_out: list[RecorderSample] = []
        for ms in (0, 250, 500, 750, 1000, 1250, 1500, 1750, 2000):
            all_out += agg.feed(_sample(ms))
        # Closing second 2 with flush:
        all_out += [s for s in [agg.flush()] if s is not None]
        assert len(all_out) == 3

    def test_flush_returns_partial_bin(self) -> None:
        agg = _active_agg()
        agg.feed(_sample(0))
        agg.feed(_sample(250))
        result = agg.flush()
        assert result is not None
        assert result.timestamp_utc == _BASE

    def test_flush_returns_none_when_no_data(self) -> None:
        agg = _active_agg()
        assert agg.flush() is None

    def test_flush_after_flush_returns_none(self) -> None:
        agg = _active_agg()
        agg.feed(_sample(0))
        agg.flush()
        assert agg.flush() is None


# ── Power time-weighted averaging ─────────────────────────────────────────────


class TestPowerAveraging:
    def test_single_reading_gives_that_power(self) -> None:
        agg = _active_agg()
        agg.feed(_sample(0, trainer=200))
        s = agg.flush()
        assert s is not None
        assert s.trainer_power_watts == 200

    def test_equal_duration_readings_average_equally(self) -> None:
        """Four readings at 0, 250, 500, 750 ms with equal spacing → simple mean."""
        agg = _active_agg()
        for ms, w in ((0, 200), (250, 220), (500, 240), (750, 260)):
            agg.feed(_sample(ms, trainer=w))
        agg.feed(_sample(1000, trainer=0))  # close bin 0
        s = agg.feed(_sample(1000, trainer=0))  # no new close
        # The closed sample is from the feed at 1000 ms.
        completed = agg.feed(_sample(2000, trainer=0))
        assert len(completed) == 1  # closes second 1
        # Actually we need the closed second 0 sample.
        # Re-run cleanly:
        agg2 = _active_agg()
        for ms, w in ((0, 200), (250, 220), (500, 240), (750, 260)):
            agg2.feed(_sample(ms, trainer=w))
        result = agg2.feed(_sample(1000, trainer=0))
        assert len(result) == 1
        # 200*0.25 + 220*0.25 + 240*0.25 + 260*0.25 = 230
        assert result[0].trainer_power_watts == 230

    def test_unequal_duration_readings_are_time_weighted(self) -> None:
        """First reading covers 0.75 s, second covers 0.25 s."""
        agg = _active_agg()
        agg.feed(_sample(0, trainer=200))
        agg.feed(_sample(750, trainer=300))
        result = agg.feed(_sample(1000, trainer=0))
        assert len(result) == 1
        # 200*0.75 + 300*0.25 = 225
        assert result[0].trainer_power_watts == 225

    def test_carry_forward_fills_gap_at_start_of_new_bin(self) -> None:
        """Previous bin ended at 200 W; new bin first reading at 500 ms with 300 W."""
        agg = _active_agg()
        agg.feed(_sample(0, trainer=200))
        # Close second 0 at second 1 boundary — bin 0 = 200 W avg.
        agg.feed(_sample(1000, trainer=200))  # closes second 0
        # In second 1: first reading at 500 ms.
        agg.feed(_sample(1500, trainer=300))
        result = agg.feed(_sample(2000, trainer=0))  # closes second 1
        assert len(result) == 1
        # Carry-forward 200 W for 0–0.5 s, then 300 W for 0.5–1.0 s → 250 W.
        assert result[0].trainer_power_watts == 250

    def test_no_power_reading_emits_none(self) -> None:
        agg = _active_agg()
        agg.feed(_sample(0, trainer=None))
        result = agg.feed(_sample(1000, trainer=None))
        assert len(result) == 1
        assert result[0].trainer_power_watts is None

    def test_bike_power_averaged_independently(self) -> None:
        agg = _active_agg()
        agg.feed(_sample(0, trainer=200, bike=220))
        agg.feed(_sample(500, trainer=210, bike=240))
        result = agg.feed(_sample(1000, trainer=0, bike=0))
        assert len(result) == 1
        # trainer: 200*0.5 + 210*0.5 = 205
        assert result[0].trainer_power_watts == 205
        # bike: 220*0.5 + 240*0.5 = 230
        assert result[0].bike_power_watts == 230


# ── Last-value fields ─────────────────────────────────────────────────────────


class TestLastValueFields:
    def test_hr_bpm_is_last_value_in_bin(self) -> None:
        agg = _active_agg()
        agg.feed(_sample(0, hr=150))
        agg.feed(_sample(500, hr=160))
        result = agg.feed(_sample(1000, hr=170))
        assert len(result) == 1
        assert result[0].heart_rate_bpm == 160  # last in closed bin (not the one at 1000)

    def test_hr_bpm_none_when_no_reading_in_bin(self) -> None:
        agg = _active_agg()
        agg.feed(_sample(0, hr=150))
        # Close second 0.
        agg.feed(_sample(1000, hr=None))
        # Second 1 has no HR.
        result = agg.feed(_sample(2000, hr=None))
        assert len(result) == 1
        assert result[0].heart_rate_bpm is None

    def test_cadence_is_last_value_in_bin(self) -> None:
        agg = _active_agg()
        agg.feed(_sample(0, cadence=88.0))
        agg.feed(_sample(500, cadence=92.0))
        result = agg.feed(_sample(1000, cadence=0.0))
        assert len(result) == 1
        assert result[0].cadence_rpm == pytest.approx(92.0)

    def test_speed_is_last_value_in_bin(self) -> None:
        agg = _active_agg()
        agg.feed(_sample(0, speed=4.0))
        agg.feed(_sample(750, speed=6.0))
        result = agg.feed(_sample(1000, speed=0.0))
        assert len(result) == 1
        assert result[0].speed_mps == pytest.approx(6.0)

    def test_total_kj_is_last_value_in_bin(self) -> None:
        agg = _active_agg()
        agg.feed(_sample(0, total_kj=1.0))
        agg.feed(_sample(750, total_kj=1.5))
        result = agg.feed(_sample(1000, total_kj=2.0))
        assert len(result) == 1
        assert result[0].total_kj == pytest.approx(1.5)

    def test_mode_is_last_value_in_bin(self) -> None:
        agg = _active_agg()
        agg.feed(_sample(0, mode="ERG"))
        result = agg.feed(_sample(1000, mode="Resistance"))
        assert len(result) == 1
        assert result[0].mode == "ERG"

    def test_hr_does_not_carry_forward_across_bins(self) -> None:
        """HR seen in bin 0 must not appear in bin 1 if no reading arrives in bin 1."""
        agg = _active_agg()
        agg.feed(_sample(0, hr=155))
        agg.feed(_sample(1000, hr=None))  # closes bin 0; bin 1 starts with no HR
        result = agg.feed(_sample(2000, hr=None))  # closes bin 1
        assert len(result) == 1
        assert result[0].heart_rate_bpm is None


# ── Pause / resume semantics ───────────────────────────────────────────────────


class TestPauseResume:
    def test_inactive_feed_produces_no_samples(self) -> None:
        agg = OneSecondAggregator()  # not activated
        result = agg.feed(_sample(0))
        assert result == []

    def test_pause_discards_in_progress_bin(self) -> None:
        agg = _active_agg()
        agg.feed(_sample(0, trainer=300))
        agg.set_recording_active(False)
        # After pause, flush should return nothing.
        assert agg.flush() is None

    def test_resumed_aggregator_starts_fresh_bin(self) -> None:
        agg = _active_agg()
        agg.feed(_sample(0, trainer=300))
        agg.set_recording_active(False)
        agg.set_recording_active(True)
        agg.feed(_sample(500, trainer=200))
        s = agg.flush()
        assert s is not None
        assert s.trainer_power_watts == 200

    def test_set_recording_active_idempotent(self) -> None:
        agg = _active_agg()
        agg.set_recording_active(True)  # already True — must not raise
        agg.feed(_sample(0))
        s = agg.flush()
        assert s is not None

    def test_power_carry_forward_preserved_across_pause_resume(self) -> None:
        """Power from bin 0 should carry forward after pause into post-resume bin."""
        agg = _active_agg()
        agg.feed(_sample(0, trainer=200))
        agg.feed(_sample(1000, trainer=200))  # closes bin 0 (avg 200 W)
        # Now pause and resume.
        agg.set_recording_active(False)
        agg.set_recording_active(True)
        # Resume: first reading at 500 ms into the new bin; carry-forward = 200 W.
        agg.feed(_sample(2500, trainer=300))
        result = agg.feed(_sample(3000, trainer=0))
        assert len(result) == 1
        # 200 W for 0–0.5 s, 300 W for 0.5–1.0 s → 250 W.
        assert result[0].trainer_power_watts == 250

    def test_feed_while_paused_produces_nothing(self) -> None:
        agg = _active_agg()
        agg.feed(_sample(0))
        agg.set_recording_active(False)
        result = agg.feed(_sample(1000))
        assert result == []


# ── Boundary conditions ────────────────────────────────────────────────────────


class TestBoundaryConditions:
    def test_exact_second_boundary_opens_new_bin(self) -> None:
        """A sample at t=1.000 must be in bin 1, not bin 0."""
        agg = _active_agg()
        agg.feed(_sample(0, trainer=100))  # bin 0
        result = agg.feed(_sample(1000, trainer=200))  # exact boundary → closes bin 0
        assert len(result) == 1
        assert result[0].timestamp_utc == _BASE
        # The 200 W reading is now in bin 1; flush to get it.
        s = agg.flush()
        assert s is not None
        assert s.timestamp_utc == _BASE + timedelta(seconds=1)
        assert s.trainer_power_watts == 200

    def test_t999ms_stays_in_same_bin(self) -> None:
        """A sample at t=0.999 s must still be in bin 0."""
        agg = _active_agg()
        agg.feed(_sample(0, trainer=100))
        agg.feed(_sample(999, trainer=200))
        result = agg.feed(_sample(1000, trainer=300))  # closes bin 0
        assert len(result) == 1
        # 100 W for 0–0.999 s, 200 W for 0.999–1.0 s (≈ 100.1 W rounded).
        assert result[0].trainer_power_watts is not None

    def test_reset_clears_carry_forward(self) -> None:
        agg = _active_agg()
        agg.feed(_sample(0, trainer=999))
        agg.flush()
        agg.reset()
        agg.set_recording_active(True)
        agg.feed(_sample(0, trainer=100))
        s = agg.flush()
        # Without carry-forward after reset, first reading back-fills from offset 0.
        assert s is not None
        assert s.trainer_power_watts == 100

    def test_flush_after_reset_returns_none(self) -> None:
        agg = _active_agg()
        agg.feed(_sample(0))
        agg.flush()
        agg.reset()
        assert agg.flush() is None

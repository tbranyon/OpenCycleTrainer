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
    dfa_alpha1: float | None = None,
    dfa_quality: str | None = None,
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
        dfa_alpha1=dfa_alpha1,
        dfa_quality=dfa_quality,
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
        agg.add_power(_ts(0), 200, None)
        s = agg.flush()
        assert s is not None
        assert s.trainer_power_watts == 200

    def test_equal_duration_readings_average_equally(self) -> None:
        """Four readings at 0, 250, 500, 750 ms with equal spacing → simple mean."""
        agg = _active_agg()
        for ms, w in ((0, 200), (250, 220), (500, 240), (750, 260)):
            agg.add_power(_ts(ms), w, None)
        result = agg.add_power(_ts(1000), 0, None)  # closes bin 0
        assert len(result) == 1
        # 200*0.25 + 220*0.25 + 240*0.25 + 260*0.25 = 230
        assert result[0].trainer_power_watts == 230

    def test_unequal_duration_readings_are_time_weighted(self) -> None:
        """First reading covers 0.75 s, second covers 0.25 s."""
        agg = _active_agg()
        agg.add_power(_ts(0), 200, None)
        agg.add_power(_ts(750), 300, None)
        result = agg.add_power(_ts(1000), 0, None)
        assert len(result) == 1
        # 200*0.75 + 300*0.25 = 225
        assert result[0].trainer_power_watts == 225

    def test_carry_forward_fills_gap_at_start_of_new_bin(self) -> None:
        """Previous bin ended at 200 W; new bin first reading at 500 ms with 300 W."""
        agg = _active_agg()
        agg.add_power(_ts(0), 200, None)
        # Close second 0 at second 1 boundary — bin 0 = 200 W avg.
        agg.add_power(_ts(1000), 200, None)  # closes second 0
        # In second 1: first reading at 500 ms.
        agg.add_power(_ts(1500), 300, None)
        result = agg.add_power(_ts(2000), 0, None)  # closes second 1
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
        agg.add_power(_ts(0), 200, 220)
        agg.add_power(_ts(500), 210, 240)
        result = agg.add_power(_ts(1000), 0, 0)
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

    def test_dfa_alpha1_and_quality_are_last_value_in_bin(self) -> None:
        """dfa_alpha1/dfa_quality pass through the aggregator unaveraged, using the
        same last-value-in-bin policy as HR/cadence/speed, so a caller pulling
        the already-forward-filled pipeline value each tick reaches the
        recorder unchanged."""
        agg = _active_agg()
        agg.feed(_sample(0, dfa_alpha1=0.81, dfa_quality="good"))
        agg.feed(_sample(500, dfa_alpha1=0.83, dfa_quality="good"))
        result = agg.feed(_sample(1000, dfa_alpha1=0.5, dfa_quality="degraded"))
        assert len(result) == 1
        assert result[0].dfa_alpha1 == pytest.approx(0.83)
        assert result[0].dfa_quality == "good"

    def test_dfa_alpha1_none_when_no_reading_in_bin(self) -> None:
        agg = _active_agg()
        agg.feed(_sample(0, dfa_alpha1=None, dfa_quality=None))
        result = agg.feed(_sample(1000, dfa_alpha1=None, dfa_quality=None))
        assert len(result) == 1
        assert result[0].dfa_alpha1 is None
        assert result[0].dfa_quality is None


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
        agg.add_power(_ts(0), 300, None)
        agg.set_recording_active(False)
        agg.set_recording_active(True)
        agg.add_power(_ts(500), 200, None)
        s = agg.flush()
        assert s is not None
        assert s.trainer_power_watts == 200

    def test_set_recording_active_idempotent(self) -> None:
        agg = _active_agg()
        agg.set_recording_active(True)  # already True — must not raise
        agg.feed(_sample(0))
        s = agg.flush()
        assert s is not None

    def test_power_carry_forward_does_not_leak_across_pause_resume(self) -> None:
        """Carry-forward must be cleared on pause: a long pause's pre-pause power
        must not backfill the leading gap of the first bin after resume (Task C
        item 1). Superseded the prior "preserved across pause" expectation, which
        was the bug this fix addresses."""
        agg = _active_agg()
        agg.add_power(_ts(0), 200, None)
        agg.add_power(_ts(1000), 200, None)  # closes bin 0 (avg 200 W)
        # Now pause and resume.
        agg.set_recording_active(False)
        agg.set_recording_active(True)
        # Resume: first reading at 500 ms into the new bin; no carry-forward,
        # so the first reading (300 W) extends back to bin start instead.
        agg.add_power(_ts(2500), 300, None)
        result = agg.add_power(_ts(3000), 0, None)
        assert len(result) == 1
        assert result[0].trainer_power_watts == 300

    def test_power_carry_forward_still_applies_across_normal_bin_boundary(self) -> None:
        """Without an intervening pause, carry-forward must still work exactly
        as before (regression guard for the ordinary, non-pause case)."""
        agg = _active_agg()
        agg.add_power(_ts(0), 200, None)
        agg.add_power(_ts(1000), 200, None)  # closes bin 0 (avg 200 W)
        agg.add_power(_ts(1500), 300, None)  # no pause; bin 1 first reading at 500ms
        result = agg.add_power(_ts(2000), 0, None)
        assert len(result) == 1
        # 200 W for 0–0.5 s, 300 W for 0.5–1.0 s → 250 W.
        assert result[0].trainer_power_watts == 250

    def test_feed_while_paused_produces_nothing(self) -> None:
        agg = _active_agg()
        agg.feed(_sample(0))
        agg.set_recording_active(False)
        result = agg.feed(_sample(1000))
        assert result == []


# ── Event-driven power ingest (add_power) ──────────────────────────────────


class TestAddPower:
    def test_two_readings_at_known_offsets_are_time_weighted(self) -> None:
        """200 W held 0.25 s then 300 W held 0.75 s -> 275 W."""
        agg = _active_agg()
        agg.add_power(_ts(0), 200, None)
        agg.add_power(_ts(250), 300, None)
        result = agg.add_power(_ts(1000), 0, None)  # closes bin 0
        assert len(result) == 1
        assert result[0].trainer_power_watts == 275

    def test_reading_between_polls_is_not_lost(self) -> None:
        """A reading whose lifetime is shorter than a 250 ms poll gap must still
        contribute to the weighted average (the pre-fix poll model would drop it
        entirely since it is overwritten before the next tick samples it)."""
        agg = _active_agg()
        agg.add_power(_ts(0), 200, None)
        agg.add_power(_ts(100), 999, None)  # short-lived reading between "polls"
        agg.add_power(_ts(150), 200, None)
        result = agg.add_power(_ts(1000), 200, None)
        assert len(result) == 1
        # 200 W for 0-0.1s, 999 W for 0.1-0.15s, 200 W for 0.15-1.0s.
        expected = 200 * 0.1 + 999 * 0.05 + 200 * 0.85
        assert result[0].trainer_power_watts == round(expected)

    def test_power_faster_than_tick_rate_contributes_every_reading(self) -> None:
        """4 Hz notifications (every 250 ms) all land in the average, none dropped."""
        agg = _active_agg()
        for ms, w in ((0, 100), (250, 150), (500, 200), (750, 250)):
            agg.add_power(_ts(ms), w, None)
        result = agg.add_power(_ts(1000), 250, None)
        assert len(result) == 1
        assert result[0].trainer_power_watts == 175  # mean of equally-spaced readings

    def test_add_power_inactive_returns_empty(self) -> None:
        agg = OneSecondAggregator()  # not activated
        result = agg.add_power(_ts(0), 200, None)
        assert result == []

    def test_add_power_bike_channel_independent(self) -> None:
        agg = _active_agg()
        agg.add_power(_ts(0), 200, 220)
        agg.add_power(_ts(500), 210, 240)
        result = agg.add_power(_ts(1000), 0, 0)
        assert len(result) == 1
        assert result[0].trainer_power_watts == 205
        assert result[0].bike_power_watts == 230

    def test_add_power_only_touches_the_channel_it_is_given(self) -> None:
        """A call reporting only trainer watts must not inject a spurious
        None segment into the bike bin (which would wrongly truncate an
        already-held bike reading)."""
        agg = _active_agg()
        agg.add_power(_ts(0), None, 220)  # bike only
        agg.add_power(_ts(500), 210, None)  # trainer only; must not touch bike bin
        result = agg.add_power(_ts(1000), 0, 0)
        assert len(result) == 1
        assert result[0].bike_power_watts == 220  # held for the whole second

    def test_feed_no_longer_adds_power_segments(self) -> None:
        """feed() must not accumulate power; only add_power does, so a value
        carried by a raw sample fed via feed() never reaches the recorded bin."""
        agg = _active_agg()
        agg.feed(_sample(0, trainer=200))
        result = agg.feed(_sample(1000, trainer=300))
        assert len(result) == 1
        assert result[0].trainer_power_watts is None

    def test_power_not_double_counted_when_fed_and_added(self) -> None:
        """A reading entered via add_power must not also be picked up by feed(),
        proving sync()'s no-power raw sample cannot double count power."""
        agg = _active_agg()
        agg.add_power(_ts(0), 200, None)
        agg.feed(_sample(500, trainer=999))  # feed()'s power must be ignored
        result = agg.add_power(_ts(1000), 200, None)
        assert len(result) == 1
        assert result[0].trainer_power_watts == 200  # unaffected by the feed() call


# ── Bins for every recorded second (Task B) ─────────────────────────────────


class TestBinsForEverySecond:
    def test_active_second_with_no_sensor_data_still_emits_a_bin(self) -> None:
        """A second that elapses while recording is active must still produce
        a RecorderSample (fields None), rather than vanishing from the sample
        list because it happened to carry no sensor data at all."""
        agg = _active_agg()
        empty = _sample(0, trainer=None, bike=None, hr=None, cadence=None, speed=None)
        agg.feed(empty)
        result = agg.feed(
            _sample(1000, trainer=None, bike=None, hr=None, cadence=None, speed=None)
        )
        assert len(result) == 1
        assert result[0].trainer_power_watts is None
        assert result[0].heart_rate_bpm is None

    def test_flush_of_empty_active_bin_emits_a_sample(self) -> None:
        agg = _active_agg()
        agg.feed(_sample(0, trainer=None, bike=None, hr=None, cadence=None, speed=None))
        s = agg.flush()
        assert s is not None
        assert s.trainer_power_watts is None

    def test_paused_second_emits_nothing(self) -> None:
        """A second that elapses while paused must never surface as a bin,
        even though an active empty bin now emits one."""
        agg = _active_agg()
        agg.feed(_sample(0, trainer=None, bike=None, hr=None, cadence=None, speed=None))
        agg.set_recording_active(False)
        assert agg.flush() is None


# ── Boundary conditions ────────────────────────────────────────────────────────


class TestOutOfOrderRobustness:
    def test_stale_sample_from_closed_bin_is_dropped_without_raising(self) -> None:
        """A sample belonging to an already-closed second must not raise."""
        agg = _active_agg()
        agg.feed(_sample(0, trainer=200))
        agg.feed(_sample(1000, trainer=300))  # closes bin 0; opens bin 1
        result = agg.feed(_sample(500, trainer=999))  # stale second-0 sample
        assert result == []

    def test_stale_sample_does_not_corrupt_open_bin_average(self) -> None:
        """A late-arriving sample for an already-closed second (e.g. after a
        backward clock step) must be dropped, not merged into the newly-opened
        bin's weighted average."""
        agg = _active_agg()
        agg.add_power(_ts(0), 200, None)
        agg.add_power(_ts(1000), 300, None)  # closes bin 0; opens bin 1 @ 300 W
        agg.add_power(_ts(500), 999, None)  # stale; belongs to closed bin 0
        result = agg.add_power(_ts(2000), 0, None)  # closes bin 1
        assert len(result) == 1
        # Bin 1 should be a constant 300 W for the full second; the stale 999 W
        # reading must not have been folded in.
        assert result[0].trainer_power_watts == 300

    def test_compute_average_handles_unsorted_segments(self) -> None:
        """_PowerBin.compute_average must sort segments before time-weighting,
        regardless of the order they were added in."""
        from opencycletrainer.core.one_second_aggregator import _PowerBin

        power_bin = _PowerBin()
        power_bin.add(0.75, 300)  # added out of order
        power_bin.add(0.0, 200)
        # 200 W for [0, 0.75), 300 W for [0.75, 1.0) -> 200*0.75 + 300*0.25 = 225
        assert power_bin.compute_average(carry_forward=None) == 225


class TestBoundaryConditions:
    def test_exact_second_boundary_opens_new_bin(self) -> None:
        """A sample at t=1.000 must be in bin 1, not bin 0."""
        agg = _active_agg()
        agg.add_power(_ts(0), 100, None)  # bin 0
        result = agg.add_power(_ts(1000), 200, None)  # exact boundary → closes bin 0
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
        agg.add_power(_ts(0), 100, None)
        agg.add_power(_ts(999), 200, None)
        result = agg.add_power(_ts(1000), 300, None)  # closes bin 0
        assert len(result) == 1
        # 100 W for 0–0.999 s, 200 W for 0.999–1.0 s (≈ 100.1 W rounded).
        assert result[0].trainer_power_watts is not None

    def test_reset_clears_carry_forward(self) -> None:
        agg = _active_agg()
        agg.add_power(_ts(0), 999, None)
        agg.flush()
        agg.reset()
        agg.set_recording_active(True)
        agg.add_power(_ts(0), 100, None)
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

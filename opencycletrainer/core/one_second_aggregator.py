from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from opencycletrainer.core.recorder import RecorderSample

# Missing-data policy:
#   trainer_power / bike_power:
#       Fed exclusively through add_power() at BLE-notification time (not feed()),
#       and aggregated using piecewise-constant time-weighted averaging. Any gap
#       at the start of a bin is filled with the last known value from the
#       previous bin (carry-forward). Carry-forward is cleared whenever recording
#       goes inactive (pause/stop) so a resume never backfills from stale
#       pre-pause power; it still applies across an ordinary bin boundary.  If no
#       carry-forward exists, the first reading in the bin is extended back to
#       bin start.  If there are no readings at all in the bin, emits None.
#   heart_rate_bpm / cadence_rpm / speed_mps / dfa_alpha1 / dfa_quality:
#       Last value seen within the bin; None if no reading arrived in this bin.
#       dfa_alpha1/dfa_quality are already forward-filled by the caller (the
#       5 s DFA pipeline's latest_record is re-read on every raw tick), so this
#       policy simply carries that value through unaveraged.
#   Every bin that closes while recording is active emits a RecorderSample, even
#   when it carries no sensor data at all (all fields None), so the recorded
#   series stays contiguous over active-recording time. A bin discarded by a
#   pause (see set_recording_active) never emits.


@dataclass
class _PowerBin:
    """Accumulates raw power readings within a single UTC-second bin."""

    segments: list[tuple[float, int | None]] = field(default_factory=list)
    # Each entry: (offset_within_second, watts).  Offset is in [0, 1).

    def add(self, offset: float, watts: int | None) -> None:
        """Append a reading at *offset* seconds from the start of this bin."""
        self.segments.append((offset, watts))

    def compute_average(self, carry_forward: int | None) -> int | None:
        """Return the time-weighted average power for this 1-second bin.

        The piecewise-constant model treats each reading as constant until the
        next reading (or bin end).  Any gap at the start of the bin is filled
        with *carry_forward*; if that is also None the first reading is extended
        back to offset 0 instead.
        """
        if not self.segments:
            return None

        # Segments may arrive out of order (e.g. a late-arriving reading); sort
        # by offset before building the effective timeline so durations are
        # never negative.
        ordered_segments = sorted(self.segments, key=lambda segment: segment[0])

        # Build the full effective timeline starting at offset 0.
        effective: list[tuple[float, int | None]] = []
        first_offset = ordered_segments[0][0]
        if first_offset > 0:
            fill = carry_forward if carry_forward is not None else ordered_segments[0][1]
            effective.append((0.0, fill))
        effective.extend(ordered_segments)

        weighted_sum = 0.0
        data_duration = 0.0
        for i, (offset, watts) in enumerate(effective):
            next_offset = effective[i + 1][0] if i + 1 < len(effective) else 1.0
            duration = next_offset - offset
            if watts is not None and duration > 0:
                weighted_sum += float(watts) * duration
                data_duration += duration

        if data_duration <= 0:
            return None
        return round(weighted_sum / data_duration)


class OneSecondAggregator:
    """Accumulates raw sensor samples and emits one RecorderSample per completed UTC second.

    Each emitted sample has its ``timestamp_utc`` set to the UTC second-floor of its bin
    (i.e. ``[N, N+1)`` convention), making FIT records deterministic and independent of
    UI timer jitter.

    Power enters via add_power() at BLE-notification time and uses piecewise-constant
    time-weighted averaging with carry-forward. HR, cadence, and speed enter via feed()
    on the poll tick and use last-value-in-bin policy (None if no reading in bin).
    """

    def __init__(self) -> None:
        self._active = False
        self._bin_second: int | None = None

        self._trainer_bin: _PowerBin = _PowerBin()
        self._bike_bin: _PowerBin = _PowerBin()
        # Carry-forward: last aggregated power from the previous bin.
        self._prev_trainer_power: int | None = None
        self._prev_bike_power: int | None = None

        # Last-value-in-bin fields (reset at each new bin).
        self._last_hr_bpm: int | None = None
        self._last_cadence_rpm: float | None = None
        self._last_speed_mps: float | None = None
        self._last_target_power: int | None = None
        self._last_mode: str | None = None
        self._last_erg_setpoint: int | None = None
        self._last_total_kj: float | None = None
        self._last_dfa_alpha1: float | None = None
        self._last_dfa_quality: str | None = None

    def set_recording_active(self, active: bool) -> None:
        """Update the aggregator's recording state.

        Transitioning to inactive discards any in-progress partial bin so that
        pause/resume restarts cleanly, and clears power carry-forward so the
        first bin after a long pause does not backfill its leading gap with
        stale pre-pause power.  Carry-forward still applies normally across an
        ordinary (non-pause) bin boundary.
        """
        active = bool(active)
        if active == self._active:
            return
        if not active:
            self._reset_bin()
            self._prev_trainer_power = None
            self._prev_bike_power = None
        self._active = active

    def feed(self, sample: RecorderSample) -> list[RecorderSample]:
        """Feed one raw sample.  Returns completed 1-second RecorderSamples (0 or more).

        A completed sample is emitted whenever the incoming timestamp crosses into a
        new UTC second.  Multiple consecutive crossings (e.g. after a gap) close only
        the current bin; intermediate empty seconds are not synthesised.

        Power is not handled here: it is fed exclusively through add_power() at
        BLE-notification time.  This only updates the last-value-in-bin channels
        (HR, cadence, speed, engine context) and the shared bin lifecycle.
        """
        if not self._active:
            return []

        ts_utc = sample.timestamp_utc.astimezone(timezone.utc)
        bin_second = int(ts_utc.timestamp())

        completed = self._advance_to(bin_second)
        if completed is None:
            return []

        self._accumulate(sample)
        return completed

    def add_power(
        self,
        timestamp_utc: datetime,
        trainer_watts: int | None,
        bike_watts: int | None,
    ) -> list[RecorderSample]:
        """Feed one power reading at its own BLE-notification timestamp.

        Unlike feed(), which samples held values on the poll tick, this enters
        power at the moment it was actually measured so time-weighted averaging
        reflects real reading lifetimes rather than poll timing.  Only the
        channel(s) with a non-None reading are updated, so a call reporting one
        channel never disturbs the other's held segments.  Returns completed
        1-second RecorderSamples (0 or more); respects self._active like feed().
        """
        if not self._active:
            return []

        ts_utc = timestamp_utc.astimezone(timezone.utc)
        bin_second = int(ts_utc.timestamp())
        offset = ts_utc.timestamp() - float(bin_second)

        completed = self._advance_to(bin_second)
        if completed is None:
            return []

        if trainer_watts is not None:
            self._trainer_bin.add(offset, trainer_watts)
        if bike_watts is not None:
            self._bike_bin.add(offset, bike_watts)
        return completed

    def flush(self) -> RecorderSample | None:
        """Flush any in-progress bin as a partial-second sample.

        Call at session end to avoid losing the last <1 s of recorded data.
        Returns None if there is nothing to flush.
        """
        if self._bin_second is None:
            return None
        return self._close_bin()

    def reset(self) -> None:
        """Reset all aggregator state.  Call at session start for a clean slate."""
        self._active = False
        self._bin_second = None
        self._trainer_bin = _PowerBin()
        self._bike_bin = _PowerBin()
        self._prev_trainer_power = None
        self._prev_bike_power = None
        self._last_hr_bpm = None
        self._last_cadence_rpm = None
        self._last_speed_mps = None
        self._last_target_power = None
        self._last_mode = None
        self._last_erg_setpoint = None
        self._last_total_kj = None
        self._last_dfa_alpha1 = None
        self._last_dfa_quality = None

    # ── Private ───────────────────────────────────────────────────────────────

    def _advance_to(self, bin_second: int) -> list[RecorderSample] | None:
        """Advance the bin lifecycle to *bin_second*, closing the previous bin
        if it was crossed.  Shared by feed() and add_power() so both entry
        points keep bin lifecycle consistent regardless of which one first
        opens or closes a given second.

        Returns a list of completed samples (0 or more) if *bin_second*
        belongs to the current or a newly-opened bin.  Returns None if
        *bin_second* belongs to an already-closed bin (e.g. the wall clock
        stepped backward mid-session), signalling the caller must not
        accumulate this reading.
        """
        completed: list[RecorderSample] = []
        if self._bin_second is None:
            self._bin_second = bin_second
        elif bin_second > self._bin_second:
            closed = self._close_bin()
            if closed is not None:
                completed.append(closed)
            self._bin_second = bin_second
        elif bin_second < self._bin_second:
            return None
        return completed

    def _accumulate(self, sample: RecorderSample) -> None:
        if sample.heart_rate_bpm is not None:
            self._last_hr_bpm = sample.heart_rate_bpm
        if sample.cadence_rpm is not None:
            self._last_cadence_rpm = sample.cadence_rpm
        if sample.speed_mps is not None:
            self._last_speed_mps = sample.speed_mps
        if sample.target_power_watts is not None:
            self._last_target_power = sample.target_power_watts
        if sample.mode is not None:
            self._last_mode = sample.mode
        if sample.erg_setpoint_watts is not None:
            self._last_erg_setpoint = sample.erg_setpoint_watts
        if sample.total_kj is not None:
            self._last_total_kj = sample.total_kj
        if sample.dfa_alpha1 is not None:
            self._last_dfa_alpha1 = sample.dfa_alpha1
        if sample.dfa_quality is not None:
            self._last_dfa_quality = sample.dfa_quality

    def _close_bin(self) -> RecorderSample | None:
        """Close the current bin, compute aggregates, and return a RecorderSample.

        Always returns a sample when a bin was open, even if it carries no
        sensor data at all (every field None), so an active-recording second
        is never silently dropped from the sample list.  Returns None only
        when no bin was open to close.
        """
        if self._bin_second is None:
            return None

        trainer_avg = self._trainer_bin.compute_average(self._prev_trainer_power)
        bike_avg = self._bike_bin.compute_average(self._prev_bike_power)

        if trainer_avg is not None:
            self._prev_trainer_power = trainer_avg
        if bike_avg is not None:
            self._prev_bike_power = bike_avg

        bin_ts = datetime.fromtimestamp(float(self._bin_second), tz=timezone.utc)
        result = RecorderSample(
            timestamp_utc=bin_ts,
            target_power_watts=self._last_target_power,
            trainer_power_watts=trainer_avg,
            bike_power_watts=bike_avg,
            heart_rate_bpm=self._last_hr_bpm,
            cadence_rpm=self._last_cadence_rpm,
            speed_mps=self._last_speed_mps,
            mode=self._last_mode,
            erg_setpoint_watts=self._last_erg_setpoint,
            total_kj=self._last_total_kj,
            dfa_alpha1=self._last_dfa_alpha1,
            dfa_quality=self._last_dfa_quality,
        )
        self._reset_bin()
        return result

    def _reset_bin(self) -> None:
        """Reset per-bin accumulation state.

        Power carry-forward is preserved here, since this is also called for
        an ordinary bin boundary; set_recording_active() clears it separately
        when recording actually goes inactive.
        """
        self._bin_second = None
        self._trainer_bin = _PowerBin()
        self._bike_bin = _PowerBin()
        # Last-value fields start fresh each bin (None = no reading yet this bin).
        self._last_hr_bpm = None
        self._last_cadence_rpm = None
        self._last_speed_mps = None
        self._last_target_power = None
        self._last_mode = None
        self._last_erg_setpoint = None
        self._last_total_kj = None
        self._last_dfa_alpha1 = None
        self._last_dfa_quality = None

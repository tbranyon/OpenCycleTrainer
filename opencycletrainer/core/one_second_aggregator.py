from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from opencycletrainer.core.recorder import RecorderSample

# Missing-data policy:
#   trainer_power / bike_power:
#       Aggregated using piecewise-constant time-weighted averaging.
#       Any gap at the start of a bin is filled with the last known value from the
#       previous bin (carry-forward).  If no carry-forward exists (start of session),
#       the first reading in the bin is extended back to bin start.
#       If there are no readings at all in the bin, emits None.
#   heart_rate_bpm / cadence_rpm / speed_mps:
#       Last value seen within the bin; None if no reading arrived in this bin.


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

        # Build the full effective timeline starting at offset 0.
        effective: list[tuple[float, int | None]] = []
        first_offset = self.segments[0][0]
        if first_offset > 0:
            fill = carry_forward if carry_forward is not None else self.segments[0][1]
            effective.append((0.0, fill))
        effective.extend(self.segments)

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

    Power aggregation uses piecewise-constant time-weighted averaging with carry-forward.
    HR, cadence, and speed use last-value-in-bin policy (None if no reading in bin).
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

    def set_recording_active(self, active: bool) -> None:
        """Update the aggregator's recording state.

        Transitioning to inactive discards any in-progress partial bin so that
        pause/resume restarts cleanly.  Power carry-forward is preserved across
        pause/resume so the first bin after resume does not start cold.
        """
        active = bool(active)
        if active == self._active:
            return
        if not active:
            self._reset_bin()
        self._active = active

    def feed(self, sample: RecorderSample) -> list[RecorderSample]:
        """Feed one raw sample.  Returns completed 1-second RecorderSamples (0 or more).

        A completed sample is emitted whenever the incoming timestamp crosses into a
        new UTC second.  Multiple consecutive crossings (e.g. after a gap) close only
        the current bin; intermediate empty seconds are not synthesised.
        """
        if not self._active:
            return []

        ts_utc = sample.timestamp_utc.astimezone(timezone.utc)
        bin_second = int(ts_utc.timestamp())
        offset = ts_utc.timestamp() - float(bin_second)

        completed: list[RecorderSample] = []

        if self._bin_second is None:
            self._bin_second = bin_second
        elif bin_second > self._bin_second:
            closed = self._close_bin()
            if closed is not None:
                completed.append(closed)
            self._bin_second = bin_second

        self._accumulate(sample, offset)
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

    # ── Private ───────────────────────────────────────────────────────────────

    def _accumulate(self, sample: RecorderSample, offset: float) -> None:
        self._trainer_bin.add(offset, sample.trainer_power_watts)
        self._bike_bin.add(offset, sample.bike_power_watts)
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

    def _close_bin(self) -> RecorderSample | None:
        """Close the current bin, compute aggregates, and return a RecorderSample."""
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
        )
        self._reset_bin()
        has_sensor_data = (
            result.trainer_power_watts is not None
            or result.bike_power_watts is not None
            or result.heart_rate_bpm is not None
            or result.cadence_rpm is not None
            or result.speed_mps is not None
        )
        return result if has_sensor_data else None

    def _reset_bin(self) -> None:
        """Reset per-bin accumulation state.  Power carry-forward is preserved."""
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

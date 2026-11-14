from __future__ import annotations

from collections import deque

from opencycletrainer.core.sensors import PowerSource
from opencycletrainer.core.time_weighted_mean import TimeWeightedMean

_POWER_SOURCE_STALENESS_SECONDS = 3.0
_NP_ROLLING_WINDOW_SECONDS = 30

# Log-spaced durations (seconds) used to build the power-duration curve.
_CURVE_DURATION_CANDIDATES = (
    1, 2, 3, 5, 8, 10, 15, 20, 30, 45, 60, 90, 120, 180, 240, 300,
    420, 600, 900, 1200, 1800, 2400, 3600, 5400, 7200, 10800, 14400,
)


class PowerHistory:
    """Rolling power sample store with workout-level aggregation."""

    def __init__(self, staleness_seconds: float = _POWER_SOURCE_STALENESS_SECONDS) -> None:
        self._staleness_seconds = float(staleness_seconds)
        self._samples: list[tuple[float, int]] = []
        self._live_samples: deque[tuple[float, int]] = deque()
        self._source_last_times: dict[PowerSource, float] = {}
        self._workout_power = TimeWeightedMean()
        self._workout_actual_kj = 0.0
        self._last_actual_power_tick: float | None = None
        self._np = _IncrementalNormalizedPower()

    def record(
        self,
        watts: int | None,
        now: float,
        recording_active: bool,
        source: PowerSource = PowerSource.TRAINER,
    ) -> bool:
        """Append an accepted power sample to the plot/stats history and live display.

        Updates the workout-level accumulators (averages, plot series, kJ). Use
        record_live() instead while paused to keep the live trailing-window display
        current without polluting the plot or workout averages.
        """
        if not self._accept_live(watts, now, source):
            return False

        self._samples.append((now, int(watts)))
        self._np.add(now, int(watts))
        self._workout_power.add(watts, now)
        if self._last_actual_power_tick is not None:
            delta = now - self._last_actual_power_tick
            if delta > 0 and recording_active:
                self._workout_actual_kj += float(watts) * delta / 1000.0
        self._last_actual_power_tick = now
        return True

    def record_live(
        self,
        watts: int | None,
        now: float,
        source: PowerSource = PowerSource.TRAINER,
    ) -> bool:
        """Append a sample to the live trailing-window display only.

        Used while paused so windowed-average tiles keep reflecting the current
        reading, without adding to the plot series, workout averages, or kJ.
        """
        return self._accept_live(watts, now, source)

    def _accept_live(
        self,
        watts: int | None,
        now: float,
        source: PowerSource,
    ) -> bool:
        """Apply source-priority gating and append to the live window; return acceptance."""
        if watts is None:
            self._source_last_times.pop(source, None)
            return False

        self._source_last_times[source] = float(now)
        if self.active_source(now) != source:
            return False

        self._live_samples.append((now, int(watts)))
        return True

    def windowed_avg(self, now: float, window_seconds: int) -> int | None:
        """Return the mean watts for all live samples within the trailing window, or None.

        Reads the live buffer so the value stays current even while paused.
        """
        cutoff = now - float(window_seconds)
        in_window = []
        for t, w in reversed(self._live_samples):
            if t < cutoff:
                break
            in_window.append(w)
        if not in_window:
            return None
        return round(sum(in_window) / len(in_window))

    def compute_normalized_power(self) -> int | None:
        """Return normalized power (30 s rolling 4th-power mean), or None if insufficient data.

        Maintained incrementally as samples arrive, so each call costs O(new seconds)
        rather than O(ride length).
        """
        result = self._np.value()
        if result is _IncrementalNormalizedPower.NEEDS_FULL_RECOMPUTE:
            return _normalized_power_from_samples(self._samples)
        return result

    def workout_avg_watts(self) -> int | None:
        """Return the time-weighted mean watts since the last reset, or None if no samples."""
        mean = self._workout_power.mean()
        return None if mean is None else round(mean)

    def workout_actual_kj(self) -> float:
        """Return measured energy (kJ) accumulated while recording was active."""
        return self._workout_actual_kj

    def active_source(self, now: float) -> PowerSource | None:
        """Return the highest-priority non-stale power source."""
        cutoff = now - self._staleness_seconds
        for source in sorted(self._source_last_times, key=lambda s: s.value):
            if self._source_last_times[source] >= cutoff:
                return source
        return None

    def reset(self) -> None:
        """Clear all samples and accumulators."""
        self._samples.clear()
        self._live_samples.clear()
        self._source_last_times.clear()
        self._workout_power.reset()
        self._workout_actual_kj = 0.0
        self._last_actual_power_tick = None
        self._np = _IncrementalNormalizedPower()

    def as_series(self) -> list[tuple[float, int]]:
        """Return all samples as a list of (monotonic_timestamp, watts) tuples."""
        return list(self._samples)

    def smoothed_series(
        self,
        window_seconds: float = 1.0,
        start_index: int = 0,
    ) -> list[tuple[float, int]]:
        """Return samples with each point replaced by the trailing time-weighted average.

        For each sample at time T, averages all samples in [T - window_seconds, T],
        weighted by the duration each value was "held" between consecutive samples.

        Only samples from *start_index* onward are returned, so callers that already
        hold the earlier points can fetch just the new tail. A point's value depends
        only on earlier samples, so the tail matches the same slice of the full series.

        Uses a sliding window pointer — O(n) — since timestamps are monotonically
        non-decreasing and the window start only ever advances forward.
        """
        samples = self._samples
        start = max(0, int(start_index))
        if start >= len(samples):
            return []
        result: list[tuple[float, int]] = []
        # Rewind from the tail to the first sample inside the first returned point's window.
        win_left = start
        first_window_start = samples[start][0] - window_seconds
        while win_left > 0 and samples[win_left - 1][0] >= first_window_start:
            win_left -= 1
        for i in range(start, len(samples)):
            t = samples[i][0]
            window_start = t - window_seconds
            while win_left < i and samples[win_left][0] < window_start:
                win_left += 1

            # The sample just before win_left is the carry-in: its value was "held"
            # from window_start until the first in-window sample.
            carry_in = samples[win_left - 1][1] if win_left > 0 else None
            in_window = samples[win_left:i + 1]

            anchor_w = carry_in if carry_in is not None else in_window[0][1]
            anchored = [(window_start, anchor_w)] + in_window

            total_weight = 0.0
            weighted_sum = 0.0
            for k in range(len(anchored) - 1):
                duration = anchored[k + 1][0] - anchored[k][0]
                weighted_sum += anchored[k][1] * duration
                total_weight += duration
            last_duration = t - anchored[-1][0]
            if last_duration > 0:
                weighted_sum += anchored[-1][1] * last_duration
                total_weight += last_duration

            avg = round(weighted_sum / total_weight) if total_weight > 0 else samples[i][1]
            result.append((t, avg))
        return result


def _normalized_power_from_samples(samples: list[tuple[float, int]]) -> int | None:
    """Compute NP from the full sample history in one pass.

    Bins samples into one-second buckets from the first sample (empty buckets count as
    0 W), takes the 30 s rolling mean, and returns the fourth root of the mean fourth power.
    """
    if len(samples) < 2:
        return None
    start_t = samples[0][0]
    end_t = samples[-1][0]
    if end_t - start_t < _NP_ROLLING_WINDOW_SECONDS:
        return None
    n_bins = int(end_t - start_t) + 1
    bins: list[list[int]] = [[] for _ in range(n_bins)]
    for t, w in samples:
        idx = min(int(t - start_t), n_bins - 1)
        bins[idx].append(w)
    one_sec = [sum(b) / len(b) if b else 0.0 for b in bins]
    if len(one_sec) < _NP_ROLLING_WINDOW_SECONDS:
        return None
    window_sum = sum(one_sec[:_NP_ROLLING_WINDOW_SECONDS])
    fourth_powers = [(window_sum / _NP_ROLLING_WINDOW_SECONDS) ** 4]
    for i in range(_NP_ROLLING_WINDOW_SECONDS, len(one_sec)):
        window_sum += one_sec[i] - one_sec[i - _NP_ROLLING_WINDOW_SECONDS]
        fourth_powers.append((window_sum / _NP_ROLLING_WINDOW_SECONDS) ** 4)
    return int(round((sum(fourth_powers) / len(fourth_powers)) ** 0.25))


class _IncrementalNormalizedPower:
    """Running state for normalized power, producing the same result as a full recompute.

    One-second bins behind the newest one can no longer change (timestamps only move
    forward), so the rolling windows ending in them are folded into running sums once.
    Each query then only adds the window ending in the newest, still-filling bin. The
    arithmetic runs in the same order as :func:`_normalized_power_from_samples`, so
    results are identical rather than merely close.
    """

    NEEDS_FULL_RECOMPUTE = object()

    def __init__(self) -> None:
        self._start_t: float | None = None
        self._end_t: float | None = None
        self._bin_sums: list[int] = []
        self._bin_counts: list[int] = []
        self._out_of_order = False
        # Windows ending at bins [WINDOW - 1, _folded_upto) are folded into these sums.
        self._folded_upto = 0
        self._window_sum = 0.0
        self._fourth_power_sum = 0.0
        self._fourth_power_count = 0

    def add(self, t: float, watts: int) -> None:
        """Add one accepted power sample."""
        if self._start_t is None:
            self._start_t = t
        if self._end_t is not None and t < self._end_t:
            self._out_of_order = True
        self._end_t = t if self._end_t is None else max(self._end_t, t)
        if self._out_of_order:
            return
        idx = int(t - self._start_t)
        while len(self._bin_sums) <= idx:
            self._bin_sums.append(0)
            self._bin_counts.append(0)
        self._bin_sums[idx] += watts
        self._bin_counts[idx] += 1

    def value(self) -> int | None | object:
        """Return NP, None when there is too little data, or NEEDS_FULL_RECOMPUTE."""
        if self._out_of_order:
            return self.NEEDS_FULL_RECOMPUTE
        if self._start_t is None or self._end_t is None or self._end_t == self._start_t:
            return None
        if self._end_t - self._start_t < _NP_ROLLING_WINDOW_SECONDS:
            return None
        last = len(self._bin_sums) - 1
        if last + 1 < _NP_ROLLING_WINDOW_SECONDS:
            return None
        self._fold_windows_before(last)
        window_sum = self._advance_window_sum(self._window_sum, last)
        fourth_sum = self._fourth_power_sum + (window_sum / _NP_ROLLING_WINDOW_SECONDS) ** 4
        count = self._fourth_power_count + 1
        return int(round((fourth_sum / count) ** 0.25))

    def _bin_mean(self, idx: int) -> float:
        count = self._bin_counts[idx]
        return self._bin_sums[idx] / count if count else 0.0

    def _advance_window_sum(self, previous_sum: float, end_idx: int) -> float:
        """Return the rolling sum for the window ending at *end_idx*, given the previous one."""
        if end_idx == _NP_ROLLING_WINDOW_SECONDS - 1:
            return sum(self._bin_mean(i) for i in range(_NP_ROLLING_WINDOW_SECONDS))
        return previous_sum + (
            self._bin_mean(end_idx) - self._bin_mean(end_idx - _NP_ROLLING_WINDOW_SECONDS)
        )

    def _fold_windows_before(self, last: int) -> None:
        """Fold every completed window (ending before the newest bin) into the running sums."""
        end_idx = max(self._folded_upto, _NP_ROLLING_WINDOW_SECONDS - 1)
        while end_idx < last:
            self._window_sum = self._advance_window_sum(self._window_sum, end_idx)
            self._fourth_power_sum += (self._window_sum / _NP_ROLLING_WINDOW_SECONDS) ** 4
            self._fourth_power_count += 1
            end_idx += 1
        self._folded_upto = max(self._folded_upto, end_idx)


def compute_power_duration_curve(samples: list[tuple[float, int]]) -> list[tuple[int, int]]:
    """Compute the mean-max power-duration curve from recorded power samples.

    Bins samples into one-second buckets, then for a fixed set of log-spaced
    durations (plus the total recorded duration) finds the highest average
    power sustained over any window of that length. Returns a list of
    ``(duration_seconds, watts)`` pairs sorted by duration.
    """
    if len(samples) < 2:
        return []

    start_t = samples[0][0]
    end_t = samples[-1][0]
    total_seconds = int(end_t - start_t)
    if total_seconds < 1:
        return []

    n_bins = total_seconds + 1
    bins: list[list[int]] = [[] for _ in range(n_bins)]
    for t, w in samples:
        idx = min(int(t - start_t), n_bins - 1)
        bins[idx].append(w)
    per_second = [sum(b) / len(b) if b else 0.0 for b in bins]

    prefix = [0.0]
    for v in per_second:
        prefix.append(prefix[-1] + v)

    durations = sorted({d for d in _CURVE_DURATION_CANDIDATES if d <= n_bins} | {n_bins})

    curve: list[tuple[int, int]] = []
    for d in durations:
        best = max(prefix[i + d] - prefix[i] for i in range(n_bins - d + 1))
        curve.append((d, round(best / d)))
    return curve

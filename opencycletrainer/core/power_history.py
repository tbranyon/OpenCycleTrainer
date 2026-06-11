from __future__ import annotations

from collections import deque

from opencycletrainer.core.sensors import PowerSource

_POWER_SOURCE_STALENESS_SECONDS = 3.0

# Log-spaced durations (seconds) used to build the power-duration curve.
_CURVE_DURATION_CANDIDATES = (
    1, 2, 3, 5, 8, 10, 15, 20, 30, 45, 60, 90, 120, 180, 240, 300,
    420, 600, 900, 1200, 1800, 2400, 3600, 5400, 7200, 10800, 14400,
)


class PowerHistory:
    """Rolling power sample store with workout-level aggregation."""

    def __init__(self, staleness_seconds: float = _POWER_SOURCE_STALENESS_SECONDS) -> None:
        self._staleness_seconds = float(staleness_seconds)
        self._samples: deque[tuple[float, int]] = deque()
        self._live_samples: deque[tuple[float, int]] = deque()
        self._source_last_times: dict[PowerSource, float] = {}
        self._workout_power_sum = 0.0
        self._workout_power_count = 0
        self._workout_actual_kj = 0.0
        self._last_actual_power_tick: float | None = None

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
        self._workout_power_sum += float(watts)
        self._workout_power_count += 1
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
        """Return normalized power (30 s rolling 4th-power mean), or None if insufficient data."""
        samples = list(self._samples)
        if len(samples) < 2:
            return None
        start_t = samples[0][0]
        end_t = samples[-1][0]
        if end_t - start_t < 30.0:
            return None
        n_bins = int(end_t - start_t) + 1
        bins: list[list[int]] = [[] for _ in range(n_bins)]
        for t, w in samples:
            idx = min(int(t - start_t), n_bins - 1)
            bins[idx].append(w)
        one_sec = [sum(b) / len(b) if b else 0.0 for b in bins]
        if len(one_sec) < 30:
            return None
        window_sum = sum(one_sec[:30])
        fourth_powers = [(window_sum / 30.0) ** 4]
        for i in range(30, len(one_sec)):
            window_sum += one_sec[i] - one_sec[i - 30]
            fourth_powers.append((window_sum / 30.0) ** 4)
        return int(round((sum(fourth_powers) / len(fourth_powers)) ** 0.25))

    def workout_avg_watts(self) -> int | None:
        """Return the mean watts since the last reset, or None if no samples."""
        if not self._workout_power_count:
            return None
        return round(self._workout_power_sum / self._workout_power_count)

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
        self._workout_power_sum = 0.0
        self._workout_power_count = 0
        self._workout_actual_kj = 0.0
        self._last_actual_power_tick = None

    def as_series(self) -> list[tuple[float, int]]:
        """Return all samples as a list of (monotonic_timestamp, watts) tuples."""
        return list(self._samples)

    def smoothed_series(self, window_seconds: float = 1.0) -> list[tuple[float, int]]:
        """Return samples with each point replaced by the trailing time-weighted average.

        For each sample at time T, averages all samples in [T - window_seconds, T],
        weighted by the duration each value was "held" between consecutive samples.

        Uses a sliding window pointer — O(n) — since timestamps are monotonically
        non-decreasing and the window start only ever advances forward.
        """
        samples = list(self._samples)
        if not samples:
            return []
        result: list[tuple[float, int]] = []
        win_left = 0  # first index with timestamp >= current window_start
        for i, (t, _) in enumerate(samples):
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

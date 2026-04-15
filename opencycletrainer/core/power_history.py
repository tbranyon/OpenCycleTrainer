from __future__ import annotations

from collections import deque


class PowerHistory:
    """Rolling power sample store with workout-level aggregation."""

    def __init__(self) -> None:
        self._samples: deque[tuple[float, int]] = deque()
        self._workout_power_sum = 0.0
        self._workout_power_count = 0
        self._workout_actual_kj = 0.0
        self._last_actual_power_tick: float | None = None

    def record(self, watts: int, now: float, recording_active: bool) -> None:
        """Append a power sample and update workout-level accumulators."""
        self._samples.append((now, int(watts)))
        self._workout_power_sum += float(watts)
        self._workout_power_count += 1
        if self._last_actual_power_tick is not None:
            delta = now - self._last_actual_power_tick
            if delta > 0 and recording_active:
                self._workout_actual_kj += float(watts) * delta / 1000.0
        self._last_actual_power_tick = now

    def windowed_avg(self, now: float, window_seconds: int) -> int | None:
        """Return the mean watts for all samples within the trailing window, or None."""
        cutoff = now - float(window_seconds)
        in_window = [w for t, w in self._samples if t >= cutoff]
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

    def reset(self) -> None:
        """Clear all samples and accumulators."""
        self._samples.clear()
        self._workout_power_sum = 0.0
        self._workout_power_count = 0
        self._workout_actual_kj = 0.0
        self._last_actual_power_tick = None

    def as_series(self) -> list[tuple[float, int]]:
        """Return all samples as a list of (monotonic_timestamp, watts) tuples."""
        return list(self._samples)

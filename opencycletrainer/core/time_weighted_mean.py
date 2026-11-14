from __future__ import annotations

# Longest a reading is credited as "in effect" when the next one is late.
# Matches the sensor staleness window used elsewhere for live display.
DEFAULT_MAX_HOLD_SECONDS = 3.0


class TimeWeightedMean:
    """Running mean of irregularly timed readings, weighted by hold time.

    Each reading is treated as in effect until the next one arrives, so a
    burst of fast notifications does not outweigh a slower stream carrying
    the same value.  The newest reading's own hold is not yet known, so it
    is credited with the same (capped) interval that preceded it; for evenly
    spaced readings this reduces to the simple mean.
    """

    def __init__(self, max_hold_seconds: float = DEFAULT_MAX_HOLD_SECONDS) -> None:
        self._max_hold_seconds = float(max_hold_seconds)
        self.reset()

    def reset(self) -> None:
        """Forget all readings."""
        self._held_sum = 0.0
        self._held_duration = 0.0
        self._last_value: float | None = None
        self._last_time: float | None = None
        self._last_delta = 0.0

    def add(self, value: float, now: float) -> None:
        """Record *value* observed at monotonic time *now*."""
        if self._last_value is not None and self._last_time is not None:
            delta = min(max(now - self._last_time, 0.0), self._max_hold_seconds)
            self._held_sum += self._last_value * delta
            self._held_duration += delta
            if delta > 0.0:
                self._last_delta = delta
        self._last_value = float(value)
        self._last_time = float(now)

    def mean(self) -> float | None:
        """Return the time-weighted mean, or None with no readings."""
        if self._last_value is None:
            return None
        total_duration = self._held_duration + self._last_delta
        if total_duration <= 0.0:
            return self._last_value
        return (self._held_sum + self._last_value * self._last_delta) / total_duration

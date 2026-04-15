from __future__ import annotations

from collections import deque

from opencycletrainer.core.sensors import CadenceSource

_WINDOWED_AVG_SECONDS = 1.0
_DROPOUT_HOLD_SECONDS = 3.0


class CadenceHistory:
    """Rolling cadence sample store with multi-source priority tracking."""

    def __init__(self, staleness_seconds: float = 3.0) -> None:
        self._staleness_seconds = staleness_seconds
        self._samples: deque[tuple[float, float]] = deque()
        self._source_last_times: dict[CadenceSource, float] = {}
        self._last_rpm: float | None = None

    def record(self, rpm: float | None, source: CadenceSource, now: float) -> None:
        """Record a cadence reading, respecting source priority order."""
        if rpm is None:
            self._source_last_times.pop(source, None)
            active = self.active_source(now)
            if active is None or active == source:
                self._last_rpm = None
            return
        self._source_last_times[source] = now
        if self.active_source(now) != source:
            return
        self._last_rpm = rpm
        self._samples.append((now, rpm))

    def last_rpm(self) -> float | None:
        """Return the most recently accepted cadence reading, or None."""
        return self._last_rpm

    def windowed_avg(self, now: float) -> int | None:
        """Return the 1 s rolling average cadence, holding the last value up to 3 s on dropout."""
        cutoff_1s = now - _WINDOWED_AVG_SECONDS
        in_window = [rpm for t, rpm in self._samples if t >= cutoff_1s]
        if in_window:
            return round(sum(in_window) / len(in_window))
        cutoff_hold = now - _DROPOUT_HOLD_SECONDS
        recent = [(t, rpm) for t, rpm in self._samples if t >= cutoff_hold]
        if recent:
            return round(max(recent, key=lambda x: x[0])[1])
        return None

    def active_source(self, now: float) -> CadenceSource | None:
        """Return the highest-priority source with a non-stale reading."""
        cutoff = now - self._staleness_seconds
        for source in sorted(self._source_last_times, key=lambda s: s.value):
            if self._source_last_times[source] >= cutoff:
                return source
        return None

    def as_deque(self) -> deque[tuple[float, float]]:
        """Return the internal sample deque (for compatibility bridges)."""
        return self._samples

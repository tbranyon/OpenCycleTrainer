from __future__ import annotations


class PedalingDetector:
    """Tracks continuous pedaling from observed power/cadence activity.

    Callers feed one boolean observation per sensor reading or tick; the detector
    reports how long the current uninterrupted pedaling run has lasted and how
    long it has been since pedaling was last seen.
    """

    def __init__(self) -> None:
        self._pedaling_since: float | None = None
        self._last_pedaling_at: float | None = None

    @property
    def is_pedaling(self) -> bool:
        """True while the most recent observation showed the rider pedaling."""
        return self._pedaling_since is not None

    @property
    def pedaling_since(self) -> float | None:
        """Monotonic time the current pedaling run began, or None when stopped."""
        return self._pedaling_since

    def update(self, now: float, *, pedaling: bool) -> None:
        """Record a pedaling observation taken at *now*."""
        if not pedaling:
            self._pedaling_since = None
            return
        if self._pedaling_since is None:
            self._pedaling_since = now
        self._last_pedaling_at = now

    def pedaling_duration(self, now: float) -> float:
        """Return the seconds of uninterrupted pedaling up to *now* (0.0 when stopped)."""
        if self._pedaling_since is None:
            return 0.0
        return max(0.0, now - self._pedaling_since)

    def seconds_since_pedaling(self, now: float) -> float | None:
        """Return the seconds since pedaling was last observed, or None if it never was."""
        if self._last_pedaling_at is None:
            return None
        return max(0.0, now - self._last_pedaling_at)

    def reset(self) -> None:
        """Forget all pedaling history."""
        self._pedaling_since = None
        self._last_pedaling_at = None

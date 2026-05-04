from __future__ import annotations


class ExternalEnergyTracker:
    """Tracks cumulative energy (kJ) from a BLE device, returning delta from first receipt.

    The device reports a running counter; this class establishes a baseline on the first
    update and exposes only the energy accumulated since that point.
    """

    def __init__(self) -> None:
        self._baseline: float | None = None
        self._current: float | None = None

    def update(self, kj: float) -> None:
        """Record the latest cumulative energy reading from the device."""
        if self._baseline is None:
            self._baseline = float(kj)
        self._current = float(kj)

    def delta_kj(self) -> float | None:
        """Return energy accumulated since the first update, or None if no data yet."""
        if self._baseline is None or self._current is None:
            return None
        return max(0.0, self._current - self._baseline)

    def has_data(self) -> bool:
        """Return True once at least one update has been received."""
        return self._baseline is not None

    def reset(self) -> None:
        """Clear all data; the next update establishes a new baseline."""
        self._baseline = None
        self._current = None

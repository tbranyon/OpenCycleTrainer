from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


class OpenTrueUpOffsetPersistence(Protocol):
    def get_offset_watts(self, trainer_id: str, power_meter_id: str) -> int:
        """Load the persisted offset for a trainer + power meter pair."""

    def set_offset_watts(self, trainer_id: str, power_meter_id: str, offset_watts: int) -> int:
        """Persist the latest computed offset for a trainer + power meter pair."""


@dataclass(frozen=True)
class OpenTrueUpStatus:
    offset_watts: int
    last_computed_offset_watts: int | None
    offset_changed: bool
    dropout_active: bool
    dropout_state_changed: bool
    requires_erg_reapply: bool


class OpenTrueUpController:
    """Offset-based correction using bike PM truth power against trainer power."""

    def __init__(
        self,
        *,
        enabled: bool = True,
        window_seconds: float = 30.0,
        update_interval_seconds: float = 5.0,
        dropout_seconds: float = 3.0,
        offset_store: OpenTrueUpOffsetPersistence | None = None,
        trainer_id: str | None = None,
        power_meter_id: str | None = None,
        initial_offset_watts: int | None = None,
    ) -> None:
        if window_seconds <= 0:
            raise ValueError("window_seconds must be greater than zero.")
        if update_interval_seconds <= 0:
            raise ValueError("update_interval_seconds must be greater than zero.")
        if dropout_seconds <= 0:
            raise ValueError("dropout_seconds must be greater than zero.")

        self._enabled = bool(enabled)
        self._window_seconds = float(window_seconds)
        self._update_interval_seconds = float(update_interval_seconds)
        self._dropout_seconds = float(dropout_seconds)
        self._offset_store = offset_store
        self._trainer_id = trainer_id
        self._power_meter_id = power_meter_id

        self._trainer_power_samples: deque[tuple[float, float]] = deque()
        self._bike_power_samples: deque[tuple[float, float]] = deque()
        self._last_sample_timestamp_seconds: float | None = None
        self._last_update_timestamp_seconds: float | None = None
        self._last_bike_sample_timestamp_seconds: float | None = None
        self._dropout_active = False
        self._last_computed_offset_watts: int | None = None
        self._last_applied_erg_target_watts: int | None = None
        self._dropout_hold_target_watts: int | None = None

        if initial_offset_watts is not None:
            self._offset_watts = int(initial_offset_watts)
        else:
            self._offset_watts = self._load_initial_offset()

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def offset_watts(self) -> int:
        return self._offset_watts

    @property
    def last_computed_offset_watts(self) -> int | None:
        return self._last_computed_offset_watts

    @property
    def dropout_active(self) -> bool:
        return self._dropout_active

    def record_power_sample(
        self,
        *,
        timestamp: datetime | float,
        trainer_power_watts: int | float | None,
        bike_power_watts: int | float | None,
    ) -> OpenTrueUpStatus:
        timestamp_seconds = _to_timestamp_seconds(timestamp)
        if (
            self._last_sample_timestamp_seconds is not None
            and timestamp_seconds < self._last_sample_timestamp_seconds
        ):
            raise ValueError("Power sample timestamps must be monotonic.")
        self._last_sample_timestamp_seconds = timestamp_seconds

        if self._last_update_timestamp_seconds is None:
            self._last_update_timestamp_seconds = timestamp_seconds

        if trainer_power_watts is not None:
            self._trainer_power_samples.append((timestamp_seconds, float(trainer_power_watts)))
        if bike_power_watts is not None:
            self._bike_power_samples.append((timestamp_seconds, float(bike_power_watts)))
            self._last_bike_sample_timestamp_seconds = timestamp_seconds

        self._trim_window(timestamp_seconds)

        prior_dropout = self._dropout_active
        self._dropout_active = self._compute_dropout_state(timestamp_seconds)
        dropout_state_changed = self._dropout_active != prior_dropout
        if dropout_state_changed:
            if self._dropout_active:
                self._dropout_hold_target_watts = self._last_applied_erg_target_watts
            else:
                self._dropout_hold_target_watts = None

        offset_changed = False
        if self._enabled and self._should_run_update(timestamp_seconds):
            self._last_update_timestamp_seconds = timestamp_seconds
            next_offset = self._compute_offset_from_window()
            if next_offset is not None:
                self._last_computed_offset_watts = next_offset
                if next_offset != self._offset_watts:
                    self._offset_watts = next_offset
                    self._persist_offset(next_offset)
                    offset_changed = True

        requires_erg_reapply = offset_changed or (
            dropout_state_changed and not self._dropout_active
        )
        return OpenTrueUpStatus(
            offset_watts=self._offset_watts,
            last_computed_offset_watts=self._last_computed_offset_watts,
            offset_changed=offset_changed,
            dropout_active=self._dropout_active,
            dropout_state_changed=dropout_state_changed,
            requires_erg_reapply=requires_erg_reapply,
        )

    def adjust_erg_target(self, base_target_watts: int, *, apply_offset: bool = True) -> int:
        base_target = int(base_target_watts)
        if base_target < 0:
            base_target = 0
        if base_target > 32767:
            base_target = 32767

        if not self._enabled or not apply_offset:
            return base_target

        if self._dropout_active and self._dropout_hold_target_watts is not None:
            target = self._dropout_hold_target_watts
        else:
            target = base_target + self._offset_watts
        target = _clamp_erg_target(target)
        self._last_applied_erg_target_watts = target
        return target

    def note_applied_erg_target(self, target_watts: int) -> None:
        self._last_applied_erg_target_watts = _clamp_erg_target(int(target_watts))
        if self._dropout_active and self._dropout_hold_target_watts is None:
            self._dropout_hold_target_watts = self._last_applied_erg_target_watts

    def _load_initial_offset(self) -> int:
        if (
            self._offset_store is None
            or self._trainer_id is None
            or self._power_meter_id is None
        ):
            return 0
        return int(
            self._offset_store.get_offset_watts(
                self._trainer_id,
                self._power_meter_id,
            ),
        )

    def _persist_offset(self, offset_watts: int) -> None:
        if (
            self._offset_store is None
            or self._trainer_id is None
            or self._power_meter_id is None
        ):
            return
        self._offset_store.set_offset_watts(
            self._trainer_id,
            self._power_meter_id,
            int(offset_watts),
        )

    def _should_run_update(self, timestamp_seconds: float) -> bool:
        assert self._last_update_timestamp_seconds is not None
        elapsed = timestamp_seconds - self._last_update_timestamp_seconds
        return elapsed >= self._update_interval_seconds

    def _compute_offset_from_window(self) -> int | None:
        if not self._trainer_power_samples or not self._bike_power_samples:
            return None
        trainer_avg = sum(sample for _, sample in self._trainer_power_samples) / len(
            self._trainer_power_samples,
        )
        bike_avg = sum(sample for _, sample in self._bike_power_samples) / len(self._bike_power_samples)
        return int(round(bike_avg - trainer_avg))

    def _trim_window(self, now_seconds: float) -> None:
        minimum_timestamp = now_seconds - self._window_seconds
        _trim_samples(self._trainer_power_samples, minimum_timestamp)
        _trim_samples(self._bike_power_samples, minimum_timestamp)

    def _compute_dropout_state(self, now_seconds: float) -> bool:
        if self._last_bike_sample_timestamp_seconds is None:
            return False
        return (now_seconds - self._last_bike_sample_timestamp_seconds) > self._dropout_seconds


def _trim_samples(samples: deque[tuple[float, float]], minimum_timestamp: float) -> None:
    while samples and samples[0][0] < minimum_timestamp:
        samples.popleft()


def _to_timestamp_seconds(value: datetime | float) -> float:
    if isinstance(value, datetime):
        return value.timestamp()
    return float(value)


def _clamp_erg_target(target_watts: int) -> int:
    if target_watts < 0:
        return 0
    if target_watts > 32767:
        return 32767
    return int(target_watts)

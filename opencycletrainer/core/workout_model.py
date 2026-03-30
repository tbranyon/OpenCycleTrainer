from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class WorkoutInterval:
    start_offset_seconds: int
    duration_seconds: int
    start_percent_ftp: float
    end_percent_ftp: float
    start_target_watts: int
    end_target_watts: int
    free_ride: bool = False

    @property
    def end_offset_seconds(self) -> int:
        return self.start_offset_seconds + self.duration_seconds

    @property
    def is_ramp(self) -> bool:
        return not math.isclose(
            self.start_percent_ftp,
            self.end_percent_ftp,
            rel_tol=1e-6,
            abs_tol=1e-6,
        )


@dataclass(frozen=True)
class Workout:
    name: str
    ftp_watts: int
    intervals: tuple[WorkoutInterval, ...]

    @property
    def total_duration_seconds(self) -> int:
        return sum(interval.duration_seconds for interval in self.intervals)


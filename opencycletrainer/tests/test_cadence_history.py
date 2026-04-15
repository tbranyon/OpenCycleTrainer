from __future__ import annotations

import pytest

from opencycletrainer.core.cadence_history import CadenceHistory
from opencycletrainer.core.sensors import CadenceSource


class TestCadenceHistoryDefaults:
    def test_last_rpm_none_when_empty(self):
        ch = CadenceHistory()
        assert ch.last_rpm() is None

    def test_windowed_avg_none_when_empty(self):
        ch = CadenceHistory()
        assert ch.windowed_avg(now=100.0) is None

    def test_active_source_none_when_empty(self):
        ch = CadenceHistory()
        assert ch.active_source(now=100.0) is None


class TestCadenceHistoryRecord:
    def test_record_updates_last_rpm(self):
        ch = CadenceHistory()
        ch.record(90.0, CadenceSource.TRAINER, now=10.0)
        assert ch.last_rpm() == 90.0

    def test_record_none_clears_last_rpm(self):
        ch = CadenceHistory()
        ch.record(90.0, CadenceSource.TRAINER, now=10.0)
        ch.record(None, CadenceSource.TRAINER, now=11.0)
        assert ch.last_rpm() is None

    def test_record_none_preserves_rpm_when_other_source_active(self):
        """Clearing a lower-priority source does not clear rpm if higher-priority is active."""
        ch = CadenceHistory()
        ch.record(90.0, CadenceSource.DEDICATED, now=10.0)
        ch.record(None, CadenceSource.TRAINER, now=11.0)
        assert ch.last_rpm() == 90.0

    def test_higher_priority_source_overrides_lower(self):
        ch = CadenceHistory()
        ch.record(70.0, CadenceSource.TRAINER, now=10.0)
        ch.record(90.0, CadenceSource.DEDICATED, now=10.5)
        assert ch.last_rpm() == 90.0

    def test_lower_priority_source_ignored_when_higher_active(self):
        ch = CadenceHistory()
        ch.record(90.0, CadenceSource.DEDICATED, now=10.0)
        ch.record(70.0, CadenceSource.TRAINER, now=10.5)
        assert ch.last_rpm() == 90.0

    def test_lower_priority_rejected_sample_not_appended(self):
        ch = CadenceHistory()
        ch.record(90.0, CadenceSource.DEDICATED, now=10.0)
        ch.record(70.0, CadenceSource.TRAINER, now=10.5)
        deque = ch.as_deque()
        assert len(deque) == 1
        assert deque[0][1] == 90.0

    def test_fallback_to_lower_priority_when_higher_goes_stale(self):
        ch = CadenceHistory(staleness_seconds=3.0)
        ch.record(90.0, CadenceSource.DEDICATED, now=10.0)
        # Advance time past staleness window so DEDICATED is stale
        ch.record(75.0, CadenceSource.POWER_METER, now=14.0)
        assert ch.last_rpm() == 75.0

    def test_power_meter_overrides_trainer(self):
        ch = CadenceHistory()
        ch.record(70.0, CadenceSource.TRAINER, now=10.0)
        ch.record(90.0, CadenceSource.POWER_METER, now=10.5)
        assert ch.last_rpm() == 90.0


class TestActiveSource:
    def test_returns_none_with_no_sources(self):
        ch = CadenceHistory()
        assert ch.active_source(now=100.0) is None

    def test_returns_only_source_when_fresh(self):
        ch = CadenceHistory(staleness_seconds=3.0)
        ch.record(80.0, CadenceSource.TRAINER, now=10.0)
        assert ch.active_source(now=10.5) == CadenceSource.TRAINER

    def test_returns_none_when_source_stale(self):
        ch = CadenceHistory(staleness_seconds=3.0)
        ch.record(80.0, CadenceSource.TRAINER, now=10.0)
        assert ch.active_source(now=14.0) is None

    def test_returns_highest_priority_when_multiple_fresh(self):
        ch = CadenceHistory(staleness_seconds=3.0)
        ch.record(80.0, CadenceSource.TRAINER, now=10.0)
        ch.record(90.0, CadenceSource.DEDICATED, now=10.5)
        assert ch.active_source(now=11.0) == CadenceSource.DEDICATED

    def test_staleness_boundary_inclusive(self):
        ch = CadenceHistory(staleness_seconds=3.0)
        ch.record(80.0, CadenceSource.TRAINER, now=10.0)
        # Exactly at boundary: now - staleness = 10.0, which is >= cutoff
        assert ch.active_source(now=13.0) == CadenceSource.TRAINER


class TestWindowedAvg:
    def test_returns_rounded_avg_within_1s_window(self):
        ch = CadenceHistory()
        ch.record(80.0, CadenceSource.TRAINER, now=10.0)
        ch.record(100.0, CadenceSource.TRAINER, now=10.5)
        assert ch.windowed_avg(now=11.0) == 90

    def test_excludes_samples_older_than_1s(self):
        ch = CadenceHistory()
        ch.record(60.0, CadenceSource.TRAINER, now=5.0)
        ch.record(90.0, CadenceSource.TRAINER, now=10.0)
        # At now=11.1: only sample at t=10.0 is within 1s
        assert ch.windowed_avg(now=11.1) == 90

    def test_holds_last_value_during_short_dropout(self):
        ch = CadenceHistory()
        ch.record(90.0, CadenceSource.TRAINER, now=10.0)
        # now=12.5: 2.5s since last sample — within 3s hold window but outside 1s active window
        assert ch.windowed_avg(now=12.5) == 90

    def test_returns_none_after_dropout_exceeds_3s(self):
        ch = CadenceHistory()
        ch.record(90.0, CadenceSource.TRAINER, now=10.0)
        assert ch.windowed_avg(now=14.0) is None

    def test_returns_none_when_no_samples(self):
        ch = CadenceHistory()
        assert ch.windowed_avg(now=100.0) is None

    def test_holds_most_recent_sample_on_dropout(self):
        ch = CadenceHistory()
        ch.record(60.0, CadenceSource.TRAINER, now=5.0)
        ch.record(90.0, CadenceSource.TRAINER, now=10.0)
        # Both samples are outside 1s window, but the most recent (90.0 at t=10.0) is within 3s
        assert ch.windowed_avg(now=12.0) == 90


class TestAsDeque:
    def test_empty_deque_when_no_samples(self):
        ch = CadenceHistory()
        assert len(ch.as_deque()) == 0

    def test_deque_contains_accepted_samples(self):
        ch = CadenceHistory()
        ch.record(80.0, CadenceSource.TRAINER, now=10.0)
        ch.record(90.0, CadenceSource.TRAINER, now=11.0)
        d = ch.as_deque()
        assert len(d) == 2
        assert d[0] == (10.0, 80.0)
        assert d[1] == (11.0, 90.0)

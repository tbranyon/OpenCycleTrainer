from __future__ import annotations

import pytest

from opencycletrainer.core.energy_tracker import ExternalEnergyTracker


class TestExternalEnergyTracker:
    def test_has_no_data_initially(self):
        tracker = ExternalEnergyTracker()
        assert not tracker.has_data()

    def test_delta_kj_is_none_initially(self):
        tracker = ExternalEnergyTracker()
        assert tracker.delta_kj() is None

    def test_has_data_after_first_update(self):
        tracker = ExternalEnergyTracker()
        tracker.update(100.0)
        assert tracker.has_data()

    def test_delta_kj_is_zero_after_first_update(self):
        tracker = ExternalEnergyTracker()
        tracker.update(100.0)
        assert tracker.delta_kj() == pytest.approx(0.0)

    def test_delta_kj_accumulates_correctly(self):
        tracker = ExternalEnergyTracker()
        tracker.update(100.0)
        tracker.update(150.0)
        assert tracker.delta_kj() == pytest.approx(50.0)

    def test_delta_kj_clamps_to_zero_when_current_below_baseline(self):
        tracker = ExternalEnergyTracker()
        tracker.update(200.0)
        tracker.update(100.0)  # device reset or wrap-around
        assert tracker.delta_kj() == pytest.approx(0.0)

    def test_reset_clears_data(self):
        tracker = ExternalEnergyTracker()
        tracker.update(100.0)
        tracker.reset()
        assert not tracker.has_data()
        assert tracker.delta_kj() is None

    def test_baseline_resets_on_next_update_after_reset(self):
        tracker = ExternalEnergyTracker()
        tracker.update(100.0)
        tracker.update(200.0)
        tracker.reset()
        tracker.update(300.0)
        assert tracker.delta_kj() == pytest.approx(0.0)

    def test_delta_accumulates_from_new_baseline_after_reset(self):
        tracker = ExternalEnergyTracker()
        tracker.update(100.0)
        tracker.reset()
        tracker.update(300.0)
        tracker.update(350.0)
        assert tracker.delta_kj() == pytest.approx(50.0)

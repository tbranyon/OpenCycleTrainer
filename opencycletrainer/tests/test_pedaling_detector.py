from __future__ import annotations

import pytest

from opencycletrainer.core.pedaling_detector import PedalingDetector


def test_new_detector_reports_no_pedaling():
    detector = PedalingDetector()

    assert detector.is_pedaling is False
    assert detector.pedaling_since is None
    assert detector.pedaling_duration(10.0) == 0.0
    assert detector.seconds_since_pedaling(10.0) is None


def test_pedaling_duration_measures_continuous_run():
    detector = PedalingDetector()

    detector.update(1.0, pedaling=True)
    detector.update(2.0, pedaling=True)

    assert detector.is_pedaling is True
    assert detector.pedaling_since == pytest.approx(1.0)
    assert detector.pedaling_duration(4.0) == pytest.approx(3.0)


def test_pedaling_duration_restarts_after_a_break():
    detector = PedalingDetector()

    detector.update(1.0, pedaling=True)
    detector.update(2.0, pedaling=False)
    detector.update(3.0, pedaling=True)

    assert detector.pedaling_since == pytest.approx(3.0)
    assert detector.pedaling_duration(5.0) == pytest.approx(2.0)


def test_seconds_since_pedaling_anchors_on_last_observation():
    """The stopped clock runs from the last observed pedaling, not from the first idle tick."""
    detector = PedalingDetector()

    detector.update(1.0, pedaling=True)
    detector.update(5.0, pedaling=False)

    assert detector.is_pedaling is False
    assert detector.seconds_since_pedaling(6.0) == pytest.approx(5.0)


def test_reset_clears_all_history():
    detector = PedalingDetector()

    detector.update(1.0, pedaling=True)
    detector.reset()

    assert detector.is_pedaling is False
    assert detector.pedaling_duration(2.0) == 0.0
    assert detector.seconds_since_pedaling(2.0) is None

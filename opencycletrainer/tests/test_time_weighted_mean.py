from __future__ import annotations

from opencycletrainer.core.time_weighted_mean import TimeWeightedMean


class TestTimeWeightedMean:
    def test_empty_is_none(self) -> None:
        assert TimeWeightedMean().mean() is None

    def test_single_reading_is_that_reading(self) -> None:
        m = TimeWeightedMean()
        m.add(200, now=1.0)
        assert m.mean() == 200.0

    def test_uniform_spacing_equals_simple_mean(self) -> None:
        m = TimeWeightedMean()
        for t, w in ((1.0, 100), (2.0, 101), (3.0, 102)):
            m.add(w, now=t)
        assert m.mean() == 101.0

    def test_each_reading_is_held_until_the_next(self) -> None:
        """4 Hz at 100 W for one second, then 1 Hz at 300 W for one second:
        the simple sample mean is 167 W but the time-weighted mean is 233 W.
        The newest reading is credited with the same hold as the interval
        that preceded it, since its own hold is not yet known."""
        m = TimeWeightedMean()
        for t in (0.0, 0.25, 0.5, 0.75):
            m.add(100, now=t)
        m.add(300, now=1.0)
        m.add(300, now=2.0)
        assert round(m.mean()) == 233

    def test_hold_is_capped_across_a_dropout(self) -> None:
        """A reading before a 9 s dropout is held for at most the cap (3 s),
        and the first reading after it is credited the same capped hold."""
        m = TimeWeightedMean(max_hold_seconds=3.0)
        m.add(100, now=0.0)
        m.add(100, now=1.0)
        m.add(300, now=10.0)
        # 100 W for 1 s + 100 W for 3 s + 300 W for 3 s over 7 s.
        assert round(m.mean()) == 186

    def test_reset_clears_everything(self) -> None:
        m = TimeWeightedMean()
        m.add(200, now=1.0)
        m.reset()
        assert m.mean() is None

    def test_non_positive_delta_is_ignored(self) -> None:
        m = TimeWeightedMean()
        m.add(100, now=1.0)
        m.add(300, now=1.0)  # duplicate timestamp: no hold accrues
        assert m.mean() == 300.0

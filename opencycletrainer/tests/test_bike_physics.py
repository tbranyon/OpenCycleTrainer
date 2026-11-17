from __future__ import annotations

import pytest

from opencycletrainer.core.bike_physics import advance_speed, resistive_force_newtons

MASS_KG = 84.0
STEP_SECONDS = 0.25
SETTLE_STEPS = 4000


def _settle(power_watts: float, grade_percent: float, *, start_mps: float = 0.0) -> float:
    """Return the speed reached after holding *power_watts* long enough to stop changing."""
    speed = start_mps
    for _ in range(SETTLE_STEPS):
        speed = advance_speed(speed, power_watts, grade_percent, MASS_KG, STEP_SECONDS)
    return speed


def test_steady_speed_balances_power_against_resistance():
    speed = _settle(200.0, 0.0)

    assert resistive_force_newtons(speed, 0.0, MASS_KG) * speed == pytest.approx(200.0, rel=0.01)


def test_flat_speed_at_endurance_power_is_realistic():
    speed_kmh = _settle(200.0, 0.0) * 3.6

    assert 28.0 < speed_kmh < 36.0


def test_climbing_is_slower_than_riding_on_the_flat():
    assert _settle(200.0, 8.0) < _settle(200.0, 0.0) / 2


def test_more_power_is_faster():
    assert _settle(300.0, 5.0) > _settle(200.0, 5.0)


def test_heavier_rider_climbs_slower():
    light = heavy = 0.0
    for _ in range(SETTLE_STEPS):
        light = advance_speed(light, 250.0, 8.0, 70.0, STEP_SECONDS)
        heavy = advance_speed(heavy, 250.0, 8.0, 100.0, STEP_SECONDS)

    assert heavy < light


def test_coasting_on_the_flat_slows_to_a_stop():
    speed = _settle(0.0, 0.0, start_mps=10.0)

    assert speed == pytest.approx(0.0, abs=0.05)


def test_speed_never_goes_negative_on_a_climb_without_power():
    speed = 3.0
    for _ in range(SETTLE_STEPS):
        speed = advance_speed(speed, 0.0, 10.0, MASS_KG, STEP_SECONDS)
        assert speed >= 0.0

    assert speed == 0.0


def test_descent_accelerates_a_stationary_rider_without_power():
    assert advance_speed(0.0, 0.0, -8.0, MASS_KG, 1.0) > 0.0


def test_descent_reaches_a_terminal_speed():
    terminal = _settle(0.0, -8.0)

    assert terminal > _settle(200.0, 0.0)
    assert advance_speed(terminal, 0.0, -8.0, MASS_KG, STEP_SECONDS) == pytest.approx(terminal, rel=1e-3)


def test_pushing_off_from_a_standstill_is_gradual():
    after_one_second = advance_speed(0.0, 300.0, 0.0, MASS_KG, 1.0)

    assert 0.0 < after_one_second < 5.0


def test_long_time_step_matches_many_short_ones():
    coarse = advance_speed(5.0, 250.0, 2.0, MASS_KG, 5.0)
    fine = 5.0
    for _ in range(50):
        fine = advance_speed(fine, 250.0, 2.0, MASS_KG, 0.1)

    assert coarse == pytest.approx(fine, rel=0.02)


def test_zero_time_step_leaves_speed_unchanged():
    assert advance_speed(7.5, 250.0, 2.0, MASS_KG, 0.0) == 7.5

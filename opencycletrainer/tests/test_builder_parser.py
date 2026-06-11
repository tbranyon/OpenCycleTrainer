from __future__ import annotations

import pytest

from opencycletrainer.core.builder_parser import is_valid_block_name, parse_builder_text


_FTP = 250


def _parse(text: str, ftp: int = _FTP, name: str = "Test", blocks=None) -> tuple:
    return parse_builder_text(text, ftp, name, blocks)


# ── Basic step types ──────────────────────────────────────────────────────────

def test_steady_percent():
    workout, errors = _parse("- 10m 100%")
    assert not errors
    assert len(workout.intervals) == 1
    iv = workout.intervals[0]
    assert iv.duration_seconds == 600
    assert iv.start_percent_ftp == pytest.approx(100.0)
    assert iv.end_percent_ftp == pytest.approx(100.0)
    assert iv.start_target_watts == 250
    assert iv.end_target_watts == 250
    assert not iv.is_ramp
    assert not iv.free_ride


def test_steady_percent_above_ftp():
    workout, errors = _parse("- 5m 110%")
    assert not errors
    iv = workout.intervals[0]
    assert iv.start_percent_ftp == pytest.approx(110.0)
    assert iv.start_target_watts == 275


def test_steady_absolute_watts():
    workout, errors = _parse("- 5m 300W")
    assert not errors
    iv = workout.intervals[0]
    assert iv.start_target_watts == 300
    assert iv.end_target_watts == 300
    assert iv.start_percent_ftp == pytest.approx(120.0)


def test_steady_absolute_watts_case_insensitive():
    workout_lower, _ = _parse("- 5m 300w")
    workout_upper, _ = _parse("- 5m 300W")
    assert workout_lower.intervals[0].start_target_watts == workout_upper.intervals[0].start_target_watts


def test_ramp_percent():
    workout, errors = _parse("- 10m ramp 50-80%")
    assert not errors
    iv = workout.intervals[0]
    assert iv.duration_seconds == 600
    assert iv.start_percent_ftp == pytest.approx(50.0)
    assert iv.end_percent_ftp == pytest.approx(80.0)
    assert iv.start_target_watts == 125
    assert iv.end_target_watts == 200
    assert iv.is_ramp


def test_ramp_watts():
    workout, errors = _parse("- 5m ramp 100-200W")
    assert not errors
    iv = workout.intervals[0]
    assert iv.start_target_watts == 100
    assert iv.end_target_watts == 200
    assert iv.is_ramp


def test_free_ride():
    workout, errors = _parse("- 5m free")
    assert not errors
    iv = workout.intervals[0]
    assert iv.free_ride
    assert iv.start_target_watts == 0
    assert iv.end_target_watts == 0


def test_freeride_alias():
    workout, _ = _parse("- 5m freeride")
    assert workout.intervals[0].free_ride


# ── Duration units ────────────────────────────────────────────────────────────

def test_duration_minutes():
    workout, _ = _parse("- 5m 100%")
    assert workout.intervals[0].duration_seconds == 300


def test_duration_seconds():
    workout, _ = _parse("- 30s 100%")
    assert workout.intervals[0].duration_seconds == 30


def test_duration_fractional_minutes():
    workout, _ = _parse("- 1.5m 100%")
    assert workout.intervals[0].duration_seconds == 90


# ── Repeat blocks ─────────────────────────────────────────────────────────────

def test_repeat_expands_correctly():
    workout, errors = _parse("- 3x(4m 110%, 2m 55%)")
    assert not errors
    assert len(workout.intervals) == 6
    # Pattern: 110%, 55%, 110%, 55%, 110%, 55%
    expected_pct = [110.0, 55.0, 110.0, 55.0, 110.0, 55.0]
    for iv, pct in zip(workout.intervals, expected_pct):
        assert iv.start_percent_ftp == pytest.approx(pct)


def test_repeat_offsets_are_sequential():
    workout, _ = _parse("- 2x(5m 100%, 3m 60%)")
    offsets = [iv.start_offset_seconds for iv in workout.intervals]
    assert offsets == [0, 300, 480, 780]


def test_repeat_mixed_with_regular_steps():
    workout, errors = _parse("- 5m 50%\n- 2x(3m 110%, 2m 55%)\n- 5m 50%")
    assert not errors
    assert len(workout.intervals) == 6  # 1 + 4 + 1


def test_repeat_omit_trailing_drops_last_step():
    # 3x(1m 120%, 1m 50%)! → work,rest,work,rest,work (last rest dropped)
    workout, errors = _parse("- 3x(1m 120%, 1m 50%)!")
    assert not errors
    assert len(workout.intervals) == 5
    expected_pct = [120.0, 50.0, 120.0, 50.0, 120.0]
    for iv, pct in zip(workout.intervals, expected_pct):
        assert iv.start_percent_ftp == pytest.approx(pct)


def test_repeat_omit_trailing_offsets():
    workout, _ = _parse("- 3x(1m 120%, 1m 50%)!")
    offsets = [iv.start_offset_seconds for iv in workout.intervals]
    assert offsets == [0, 60, 120, 180, 240]


def test_repeat_omit_trailing_single_rep():
    # 1x(1m 120%, 1m 50%)! → only the work interval
    workout, errors = _parse("- 1x(1m 120%, 1m 50%)!")
    assert not errors
    assert len(workout.intervals) == 1
    assert workout.intervals[0].start_percent_ftp == pytest.approx(120.0)


def test_repeat_without_bang_unchanged():
    # Ensure omit-trailing syntax does not break normal repeat
    workout, errors = _parse("- 3x(1m 120%, 1m 50%)")
    assert not errors
    assert len(workout.intervals) == 6


def test_repeat_omit_trailing_mixed_with_regular_steps():
    workout, errors = _parse("- 5m 50%\n- 3x(1m 120%, 1m 50%)!\n- 5m 50%")
    assert not errors
    assert len(workout.intervals) == 7  # 1 + 5 + 1


# ── Reusable blocks ───────────────────────────────────────────────────────────

def test_block_reference_expands_to_block_steps():
    blocks = {"warmup": "- 5m 50%\n- 1m ramp 50-70%"}
    workout, errors = _parse("- @warmup", blocks=blocks)
    assert not errors
    assert len(workout.intervals) == 2
    assert workout.intervals[0].duration_seconds == 300
    assert workout.intervals[0].start_percent_ftp == pytest.approx(50.0)
    assert workout.intervals[1].is_ramp


def test_block_reference_offsets_accumulate_with_surrounding_steps():
    blocks = {"warmup": "- 5m 50%\n- 5m 60%"}
    workout, _ = _parse("- @warmup\n- 10m 90%", blocks=blocks)
    offsets = [iv.start_offset_seconds for iv in workout.intervals]
    assert offsets == [0, 300, 600]
    assert workout.total_duration_seconds == 20 * 60


def test_block_can_contain_repeat():
    blocks = {"set": "- 3x(4m 110%, 2m 55%)"}
    workout, errors = _parse("- @set", blocks=blocks)
    assert not errors
    assert len(workout.intervals) == 6


def test_block_mixed_with_regular_and_repeat_steps():
    blocks = {"warmup": "- 5m 50%", "cooldown": "- 5m 50%"}
    workout, errors = _parse(
        "- @warmup\n- 2x(3m 110%, 2m 55%)\n- @cooldown", blocks=blocks
    )
    assert not errors
    assert len(workout.intervals) == 6  # 1 + 4 + 1


def test_unknown_block_reference_is_non_fatal():
    blocks = {"warmup": "- 5m 50%"}
    workout, errors = _parse("- @missing\n- 10m 90%", blocks=blocks)
    assert errors
    assert "missing" in errors[0]
    assert len(workout.intervals) == 1  # the valid step still parses


def test_block_reference_without_blocks_provided_is_error():
    workout, errors = _parse("- @warmup")
    assert errors
    assert len(workout.intervals) == 0


def test_nested_block_reference_is_an_error():
    blocks = {"warmup": "- 5m 50%", "combo": "- @warmup\n- 5m 90%"}
    workout, errors = _parse("- @combo", blocks=blocks)
    assert errors
    # The valid step inside the block still expands; only the nested @ref fails.
    assert len(workout.intervals) == 1
    assert workout.intervals[0].start_percent_ftp == pytest.approx(90.0)


def test_is_valid_block_name():
    assert is_valid_block_name("warmup")
    assert is_valid_block_name("Warm Up 1")
    assert is_valid_block_name("cool-down_2")
    assert not is_valid_block_name("")
    assert not is_valid_block_name(" leading")
    assert not is_valid_block_name("bad@name")


# ── Comments and blank lines ──────────────────────────────────────────────────

def test_comment_lines_are_ignored():
    workout, errors = _parse("# warm up\n- 10m 50%\n# main set\n- 20m 95%")
    assert not errors
    assert len(workout.intervals) == 2


def test_blank_lines_are_ignored():
    workout, _ = _parse("\n- 5m 50%\n\n- 10m 90%\n")
    assert len(workout.intervals) == 2


# ── Offset accumulation ───────────────────────────────────────────────────────

def test_intervals_have_correct_offsets():
    workout, _ = _parse("- 10m 50%\n- 20m 95%\n- 5m 50%")
    assert workout.intervals[0].start_offset_seconds == 0
    assert workout.intervals[1].start_offset_seconds == 600
    assert workout.intervals[2].start_offset_seconds == 1800


def test_total_duration():
    workout, _ = _parse("- 10m 50%\n- 20m 95%\n- 5m 50%")
    assert workout.total_duration_seconds == 35 * 60


# ── Error handling ────────────────────────────────────────────────────────────

def test_line_without_dash_is_an_error():
    workout, errors = _parse("5m 100%")
    assert len(errors) == 1
    assert "Line 1" in errors[0]


def test_invalid_duration_is_an_error():
    workout, errors = _parse("- abc 100%")
    assert errors


def test_missing_power_is_an_error():
    workout, errors = _parse("- 5m")
    assert errors


def test_unrecognized_power_spec_is_an_error():
    workout, errors = _parse("- 5m superhard")
    assert errors


def test_errors_are_non_fatal_partial_workout_returned():
    workout, errors = _parse("- 5m 110%\nbad line\n- 3m 80%")
    assert errors
    assert len(workout.intervals) == 2  # valid lines still produce intervals


def test_empty_text_returns_empty_workout():
    workout, errors = _parse("")
    assert not errors
    assert len(workout.intervals) == 0


def test_workout_name_propagated():
    workout, _ = _parse("- 5m 100%", name="My Workout")
    assert workout.name == "My Workout"


def test_fallback_name_when_empty():
    workout, _ = _parse("- 5m 100%", name="")
    assert workout.name == "Untitled"


def test_ftp_propagated_to_workout():
    workout, _ = _parse("- 5m 100%", ftp=300)
    assert workout.ftp_watts == 300

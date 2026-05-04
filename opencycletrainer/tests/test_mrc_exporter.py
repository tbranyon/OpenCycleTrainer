from __future__ import annotations

from opencycletrainer.core.builder_parser import parse_builder_text
from opencycletrainer.core.mrc_exporter import workout_to_mrc_text
from opencycletrainer.core.mrc_parser import parse_mrc_text


_FTP = 250


def _workout(text: str):
    w, _ = parse_builder_text(text, _FTP, "Test")
    return w


def _roundtrip(text: str):
    workout = _workout(text)
    mrc = workout_to_mrc_text(workout)
    return parse_mrc_text(mrc, _FTP, "Test")


# ── Structure ─────────────────────────────────────────────────────────────────

def test_output_contains_required_sections():
    mrc = workout_to_mrc_text(_workout("- 10m 80%"))
    assert "[COURSE HEADER]" in mrc
    assert "[END COURSE HEADER]" in mrc
    assert "[COURSE DATA]" in mrc
    assert "[END COURSE DATA]" in mrc


def test_output_contains_description():
    w, _ = parse_builder_text("- 10m 80%", _FTP, "My Workout")
    mrc = workout_to_mrc_text(w)
    assert "DESCRIPTION = My Workout" in mrc


def test_category_included_when_provided():
    mrc = workout_to_mrc_text(_workout("- 10m 80%"), category="SST")
    assert "CATEGORY = SST" in mrc


def test_category_omitted_when_empty():
    mrc = workout_to_mrc_text(_workout("- 10m 80%"), category="")
    assert "CATEGORY" not in mrc


def test_minutes_percent_header_present():
    mrc = workout_to_mrc_text(_workout("- 10m 80%"))
    assert "MINUTES PERCENT" in mrc


# ── Round-trip correctness ────────────────────────────────────────────────────

def test_roundtrip_steady_state_interval_count():
    original = _workout("- 10m 50%\n- 20m 95%\n- 5m 50%")
    rt = _roundtrip("- 10m 50%\n- 20m 95%\n- 5m 50%")
    assert len(rt.intervals) == len(original.intervals)


def test_roundtrip_steady_state_durations():
    rt = _roundtrip("- 10m 50%\n- 20m 95%\n- 5m 50%")
    assert [iv.duration_seconds for iv in rt.intervals] == [600, 1200, 300]


def test_roundtrip_steady_state_power():
    rt = _roundtrip("- 10m 50%\n- 20m 95%\n- 5m 50%")
    assert [iv.start_percent_ftp for iv in rt.intervals] == [50.0, 95.0, 50.0]


def test_roundtrip_ramp():
    rt = _roundtrip("- 10m ramp 50-80%")
    assert len(rt.intervals) == 1
    iv = rt.intervals[0]
    assert iv.start_percent_ftp == 50.0
    assert iv.end_percent_ftp == 80.0
    assert iv.is_ramp


def test_roundtrip_repeated_intervals():
    rt = _roundtrip("- 3x(4m 110%, 2m 55%)")
    assert len(rt.intervals) == 6


def test_roundtrip_preserves_total_duration():
    builder_text = "- 10m 50%\n- 20m 95%\n- 5m 50%"
    original = _workout(builder_text)
    rt = _roundtrip(builder_text)
    assert rt.total_duration_seconds == original.total_duration_seconds

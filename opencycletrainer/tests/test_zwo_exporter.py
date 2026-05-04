from __future__ import annotations

import xml.etree.ElementTree as ET

from opencycletrainer.core.builder_parser import parse_builder_text
from opencycletrainer.core.zwo_exporter import workout_to_zwo_text
from opencycletrainer.core.zwo_parser import parse_zwo_text


_FTP = 250


def _workout(text: str):
    w, _ = parse_builder_text(text, _FTP, "Test")
    return w


def _roundtrip(text: str):
    workout = _workout(text)
    zwo = workout_to_zwo_text(workout)
    return parse_zwo_text(zwo, _FTP, "Test")


# ── Structure ─────────────────────────────────────────────────────────────────

def test_output_is_valid_xml():
    zwo = workout_to_zwo_text(_workout("- 10m 80%"))
    ET.fromstring(zwo.split("\n", 1)[1])  # strip XML declaration before parsing


def test_output_has_xml_declaration():
    zwo = workout_to_zwo_text(_workout("- 10m 80%"))
    assert zwo.startswith('<?xml version="1.0" encoding="UTF-8"?>')


def test_output_contains_name():
    w, _ = parse_builder_text("- 10m 80%", _FTP, "My Workout")
    zwo = workout_to_zwo_text(w)
    assert "<name>My Workout</name>" in zwo


def test_category_stored_in_oct_category():
    zwo = workout_to_zwo_text(_workout("- 10m 80%"), category="Base")
    assert "<oct_category>Base</oct_category>" in zwo


def test_category_omitted_when_empty():
    zwo = workout_to_zwo_text(_workout("- 10m 80%"), category="")
    assert "oct_category" not in zwo


def test_steady_state_emits_steadystate_element():
    zwo = workout_to_zwo_text(_workout("- 10m 80%"))
    assert "SteadyState" in zwo


def test_ramp_emits_ramp_element():
    zwo = workout_to_zwo_text(_workout("- 10m ramp 50-80%"))
    assert "Ramp" in zwo


def test_free_ride_emits_freeride_element():
    zwo = workout_to_zwo_text(_workout("- 5m free"))
    assert "FreeRide" in zwo


# ── Round-trip correctness ────────────────────────────────────────────────────

def test_roundtrip_steady_state_interval_count():
    rt = _roundtrip("- 10m 50%\n- 20m 95%\n- 5m 50%")
    assert len(rt.intervals) == 3


def test_roundtrip_steady_state_power():
    rt = _roundtrip("- 10m 50%\n- 20m 95%\n- 5m 50%")
    assert rt.intervals[0].start_percent_ftp == 50.0
    assert rt.intervals[1].start_percent_ftp == 95.0


def test_roundtrip_steady_state_durations():
    rt = _roundtrip("- 10m 50%\n- 20m 95%\n- 5m 50%")
    assert [iv.duration_seconds for iv in rt.intervals] == [600, 1200, 300]


def test_roundtrip_ramp():
    rt = _roundtrip("- 10m ramp 50-80%")
    iv = rt.intervals[0]
    assert iv.start_percent_ftp == 50.0
    assert iv.end_percent_ftp == 80.0
    assert iv.is_ramp


def test_roundtrip_free_ride():
    rt = _roundtrip("- 5m free\n- 10m 80%")
    assert rt.intervals[0].free_ride
    assert not rt.intervals[1].free_ride


def test_roundtrip_mixed_workout():
    rt = _roundtrip("- 10m 50%\n- 5m ramp 60-90%\n- 5m free\n- 10m 50%")
    assert len(rt.intervals) == 4
    assert not rt.intervals[0].is_ramp
    assert rt.intervals[1].is_ramp
    assert rt.intervals[2].free_ride
    assert not rt.intervals[3].free_ride


def test_roundtrip_preserves_total_duration():
    builder_text = "- 5m free\n- 10m 80%\n- 5m 50%"
    original = _workout(builder_text)
    rt = _roundtrip(builder_text)
    assert rt.total_duration_seconds == original.total_duration_seconds

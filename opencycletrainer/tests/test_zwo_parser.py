from __future__ import annotations

from pathlib import Path
import textwrap

import pytest

from opencycletrainer.core.zwo_parser import (
    ZWOParseError,
    inject_category_into_zwo_text,
    parse_zwo_file,
    parse_zwo_header,
    parse_zwo_text,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _wrap(inner_xml: str, name: str = "Test Workout") -> str:
    """Wrap segment XML in a minimal valid ZWO document."""
    return textwrap.dedent(f"""\
        <workout_file>
          <name>{name}</name>
          <description>A test workout</description>
          <sportType>bike</sportType>
          <workout>
            {inner_xml}
          </workout>
        </workout_file>
    """)


FTP = 200


# ── SteadyState ───────────────────────────────────────────────────────────────

def test_steady_state_produces_flat_interval():
    zwo = _wrap('<SteadyState Duration="600" Power="0.85"/>')
    workout = parse_zwo_text(zwo, ftp_watts=FTP)

    assert len(workout.intervals) == 1
    iv = workout.intervals[0]
    assert iv.duration_seconds == 600
    assert iv.start_percent_ftp == pytest.approx(85.0)
    assert iv.end_percent_ftp == pytest.approx(85.0)
    assert iv.is_ramp is False
    assert iv.free_ride is False
    assert iv.start_target_watts == 170
    assert iv.end_target_watts == 170


def test_steady_state_start_offset_zero():
    zwo = _wrap('<SteadyState Duration="300" Power="0.75"/>')
    workout = parse_zwo_text(zwo, ftp_watts=FTP)
    assert workout.intervals[0].start_offset_seconds == 0


# ── Warmup ────────────────────────────────────────────────────────────────────

def test_warmup_produces_ramp_interval():
    zwo = _wrap('<Warmup Duration="300" PowerLow="0.25" PowerHigh="0.75"/>')
    workout = parse_zwo_text(zwo, ftp_watts=FTP)

    assert len(workout.intervals) == 1
    iv = workout.intervals[0]
    assert iv.duration_seconds == 300
    assert iv.start_percent_ftp == pytest.approx(25.0)
    assert iv.end_percent_ftp == pytest.approx(75.0)
    assert iv.is_ramp is True
    assert iv.free_ride is False
    assert iv.start_target_watts == 50
    assert iv.end_target_watts == 150


# ── Cooldown ──────────────────────────────────────────────────────────────────

def test_cooldown_produces_ramp_interval():
    zwo = _wrap('<Cooldown Duration="300" PowerLow="0.75" PowerHigh="0.25"/>')
    workout = parse_zwo_text(zwo, ftp_watts=FTP)

    assert len(workout.intervals) == 1
    iv = workout.intervals[0]
    assert iv.duration_seconds == 300
    assert iv.start_percent_ftp == pytest.approx(75.0)
    assert iv.end_percent_ftp == pytest.approx(25.0)
    assert iv.is_ramp is True
    assert iv.free_ride is False


# ── Ramp ──────────────────────────────────────────────────────────────────────

def test_ramp_produces_ramp_interval():
    zwo = _wrap('<Ramp Duration="300" PowerLow="0.50" PowerHigh="0.80"/>')
    workout = parse_zwo_text(zwo, ftp_watts=FTP)

    assert len(workout.intervals) == 1
    iv = workout.intervals[0]
    assert iv.start_percent_ftp == pytest.approx(50.0)
    assert iv.end_percent_ftp == pytest.approx(80.0)
    assert iv.is_ramp is True
    assert iv.free_ride is False


# ── IntervalsT ────────────────────────────────────────────────────────────────

def test_intervals_t_repeat_3_produces_6_intervals():
    zwo = _wrap(
        '<IntervalsT Repeat="3" OnDuration="60" OffDuration="60"'
        ' OnPower="1.20" OffPower="0.50"/>'
    )
    workout = parse_zwo_text(zwo, ftp_watts=FTP)

    assert len(workout.intervals) == 6
    for i, iv in enumerate(workout.intervals):
        assert iv.free_ride is False
        assert iv.duration_seconds == 60
        if i % 2 == 0:
            # ON interval
            assert iv.start_percent_ftp == pytest.approx(120.0)
            assert iv.end_percent_ftp == pytest.approx(120.0)
            assert iv.is_ramp is False
        else:
            # OFF interval
            assert iv.start_percent_ftp == pytest.approx(50.0)
            assert iv.end_percent_ftp == pytest.approx(50.0)
            assert iv.is_ramp is False


def test_intervals_t_start_offsets_are_sequential():
    zwo = _wrap(
        '<IntervalsT Repeat="2" OnDuration="30" OffDuration="90"'
        ' OnPower="1.10" OffPower="0.60"/>'
    )
    workout = parse_zwo_text(zwo, ftp_watts=FTP)

    assert len(workout.intervals) == 4
    assert workout.intervals[0].start_offset_seconds == 0
    assert workout.intervals[1].start_offset_seconds == 30
    assert workout.intervals[2].start_offset_seconds == 120
    assert workout.intervals[3].start_offset_seconds == 150


# ── FreeRide ──────────────────────────────────────────────────────────────────

def test_free_ride_produces_free_ride_interval():
    zwo = _wrap('<FreeRide Duration="300"/>')
    workout = parse_zwo_text(zwo, ftp_watts=FTP)

    assert len(workout.intervals) == 1
    iv = workout.intervals[0]
    assert iv.free_ride is True
    assert iv.duration_seconds == 300
    assert iv.start_target_watts == 0
    assert iv.end_target_watts == 0
    assert iv.start_percent_ftp == pytest.approx(0.0)
    assert iv.end_percent_ftp == pytest.approx(0.0)


# ── MaxEffort ─────────────────────────────────────────────────────────────────

def test_max_effort_produces_free_ride_interval():
    zwo = _wrap('<MaxEffort Duration="30"/>')
    workout = parse_zwo_text(zwo, ftp_watts=FTP)

    assert len(workout.intervals) == 1
    iv = workout.intervals[0]
    assert iv.free_ride is True
    assert iv.duration_seconds == 30
    assert iv.start_target_watts == 0
    assert iv.end_target_watts == 0


# ── Mixed workout: offsets ─────────────────────────────────────────────────────

def test_mixed_workout_start_offsets():
    """normal → FreeRide → normal: start_offset_seconds correct on all."""
    zwo = _wrap(
        '<SteadyState Duration="300" Power="0.65"/>\n'
        '    <FreeRide Duration="120"/>\n'
        '    <SteadyState Duration="60" Power="0.90"/>'
    )
    workout = parse_zwo_text(zwo, ftp_watts=FTP)

    assert len(workout.intervals) == 3
    assert workout.intervals[0].start_offset_seconds == 0
    assert workout.intervals[0].duration_seconds == 300
    assert workout.intervals[1].start_offset_seconds == 300
    assert workout.intervals[1].duration_seconds == 120
    assert workout.intervals[2].start_offset_seconds == 420
    assert workout.intervals[2].duration_seconds == 60


# ── Workout name ──────────────────────────────────────────────────────────────

def test_workout_name_from_name_element():
    zwo = _wrap('<SteadyState Duration="300" Power="0.75"/>', name="My ZWO Workout")
    workout = parse_zwo_text(zwo, ftp_watts=FTP)
    assert workout.name == "My ZWO Workout"


def test_workout_name_falls_back_to_fallback_when_name_missing():
    zwo = textwrap.dedent("""\
        <workout_file>
          <workout>
            <SteadyState Duration="300" Power="0.75"/>
          </workout>
        </workout_file>
    """)
    workout = parse_zwo_text(zwo, ftp_watts=FTP, fallback_workout_name="Fallback")
    assert workout.name == "Fallback"


def test_workout_name_falls_back_to_default_when_name_empty():
    zwo = textwrap.dedent("""\
        <workout_file>
          <name>   </name>
          <workout>
            <SteadyState Duration="300" Power="0.75"/>
          </workout>
        </workout_file>
    """)
    workout = parse_zwo_text(zwo, ftp_watts=FTP)
    assert workout.name == "Workout"


# ── parse_zwo_header ──────────────────────────────────────────────────────────

def test_parse_zwo_header_returns_all_fields():
    zwo = textwrap.dedent("""\
        <workout_file>
          <name>Header Test</name>
          <description>A description</description>
          <sportType>bike</sportType>
          <workout>
            <SteadyState Duration="300" Power="0.75"/>
          </workout>
        </workout_file>
    """)
    header = parse_zwo_header(zwo)
    assert header["name"] == "Header Test"
    assert header["description"] == "A description"
    assert header["sportType"] == "bike"
    assert header["category"] == ""


def test_parse_zwo_header_returns_category_when_present():
    zwo = textwrap.dedent("""\
        <workout_file>
          <name>Cat Test</name>
          <workout>
            <SteadyState Duration="300" Power="0.75"/>
          </workout>
          <oct_category>SST</oct_category>
        </workout_file>
    """)
    header = parse_zwo_header(zwo)
    assert header["category"] == "SST"


def test_parse_zwo_header_missing_fields_return_empty_string():
    zwo = textwrap.dedent("""\
        <workout_file>
          <workout>
            <SteadyState Duration="300" Power="0.75"/>
          </workout>
        </workout_file>
    """)
    header = parse_zwo_header(zwo)
    assert header["name"] == ""
    assert header["description"] == ""
    assert header["category"] == ""


# ── inject_category_into_zwo_text ─────────────────────────────────────────────

_ZWO_NO_CAT = textwrap.dedent("""\
    <workout_file>
      <name>Test</name>
      <workout>
        <SteadyState Duration="300" Power="0.75"/>
      </workout>
    </workout_file>
""")

_ZWO_WITH_CAT = textwrap.dedent("""\
    <workout_file>
      <name>Test</name>
      <workout>
        <SteadyState Duration="300" Power="0.75"/>
      </workout>
      <oct_category>OldCat</oct_category>
    </workout_file>
""")


def test_inject_category_inserts_when_absent():
    result = inject_category_into_zwo_text(_ZWO_NO_CAT, "SST")
    header = parse_zwo_header(result)
    assert header["category"] == "SST"


def test_inject_category_replaces_when_present():
    result = inject_category_into_zwo_text(_ZWO_WITH_CAT, "Threshold")
    header = parse_zwo_header(result)
    assert header["category"] == "Threshold"
    assert result.count("oct_category") == 2  # open + close tag


def test_inject_category_old_value_gone():
    result = inject_category_into_zwo_text(_ZWO_WITH_CAT, "Threshold")
    assert "OldCat" not in result


def test_inject_category_roundtrips():
    result = inject_category_into_zwo_text(_ZWO_NO_CAT, "VO2max")
    assert parse_zwo_header(result)["category"] == "VO2max"
    # Apply again with a different category
    result2 = inject_category_into_zwo_text(result, "Z2")
    assert parse_zwo_header(result2)["category"] == "Z2"


# ── Error cases ───────────────────────────────────────────────────────────────

def test_parse_zwo_text_rejects_bad_xml():
    with pytest.raises(ZWOParseError, match="XML"):
        parse_zwo_text("not xml at all<<<", ftp_watts=FTP)


def test_parse_zwo_text_rejects_missing_workout_element():
    zwo = "<workout_file><name>X</name></workout_file>"
    with pytest.raises(ZWOParseError, match="workout"):
        parse_zwo_text(zwo, ftp_watts=FTP)


def test_parse_zwo_text_rejects_zero_intervals():
    zwo = "<workout_file><workout></workout></workout_file>"
    with pytest.raises(ZWOParseError):
        parse_zwo_text(zwo, ftp_watts=FTP)


def test_parse_zwo_text_rejects_invalid_ftp():
    zwo = _wrap('<SteadyState Duration="300" Power="0.75"/>')
    with pytest.raises(ZWOParseError, match="FTP"):
        parse_zwo_text(zwo, ftp_watts=0)


def test_parse_zwo_text_rejects_missing_required_attribute():
    # SteadyState missing Power
    zwo = _wrap('<SteadyState Duration="300"/>')
    with pytest.raises(ZWOParseError):
        parse_zwo_text(zwo, ftp_watts=FTP)


def test_parse_zwo_text_rejects_non_numeric_power():
    zwo = _wrap('<SteadyState Duration="300" Power="hard"/>')
    with pytest.raises(ZWOParseError):
        parse_zwo_text(zwo, ftp_watts=FTP)


def test_parse_zwo_text_rejects_non_numeric_duration():
    zwo = _wrap('<SteadyState Duration="long" Power="0.75"/>')
    with pytest.raises(ZWOParseError):
        parse_zwo_text(zwo, ftp_watts=FTP)


# ── parse_zwo_file ────────────────────────────────────────────────────────────

def test_parse_zwo_file_reads_from_disk(tmp_path):
    zwo_text = _wrap('<SteadyState Duration="600" Power="0.90"/>', name="File Test")
    zwo_file = tmp_path / "test_workout.zwo"
    zwo_file.write_text(zwo_text, encoding="utf-8")

    workout = parse_zwo_file(zwo_file, ftp_watts=FTP)
    assert workout.name == "File Test"
    assert len(workout.intervals) == 1
    assert workout.intervals[0].duration_seconds == 600


def test_parse_zwo_file_uses_stem_as_fallback_name(tmp_path):
    zwo_text = textwrap.dedent("""\
        <workout_file>
          <workout>
            <SteadyState Duration="300" Power="0.75"/>
          </workout>
        </workout_file>
    """)
    zwo_file = tmp_path / "my_workout.zwo"
    zwo_file.write_text(zwo_text, encoding="utf-8")

    workout = parse_zwo_file(zwo_file, ftp_watts=FTP)
    assert workout.name == "my_workout"

from __future__ import annotations

from pathlib import Path

import pytest

from opencycletrainer.core.mrc_parser import (
    MRCParseError,
    inject_category_into_mrc_text,
    parse_mrc_file,
    parse_mrc_header,
    parse_mrc_text,
)


TEST_DATA_DIR = Path(__file__).parent / "data"


def test_parse_step_only_mrc_produces_step_intervals():
    workout = parse_mrc_file(TEST_DATA_DIR / "step_only.mrc", ftp_watts=300)

    assert workout.name == "Step Session"
    assert len(workout.intervals) == 3
    assert [interval.duration_seconds for interval in workout.intervals] == [300, 300, 300]
    assert [interval.start_percent_ftp for interval in workout.intervals] == [50.0, 75.0, 90.0]
    assert [interval.end_percent_ftp for interval in workout.intervals] == [50.0, 75.0, 90.0]
    assert [interval.is_ramp for interval in workout.intervals] == [False, False, False]
    assert [interval.start_target_watts for interval in workout.intervals] == [150, 225, 270]
    assert [interval.end_target_watts for interval in workout.intervals] == [150, 225, 270]


def test_parse_ramp_mrc_produces_ramp_intervals():
    workout = parse_mrc_file(TEST_DATA_DIR / "ramp.mrc", ftp_watts=250)

    assert workout.name == "Ramp Session"
    assert len(workout.intervals) == 3
    assert [interval.duration_seconds for interval in workout.intervals] == [300, 300, 300]
    assert [interval.start_percent_ftp for interval in workout.intervals] == [50.0, 65.0, 80.0]
    assert [interval.end_percent_ftp for interval in workout.intervals] == [65.0, 80.0, 55.0]
    assert [interval.is_ramp for interval in workout.intervals] == [True, True, True]
    assert [interval.start_target_watts for interval in workout.intervals] == [125, 163, 200]
    assert [interval.end_target_watts for interval in workout.intervals] == [163, 200, 138]


def test_parse_mrc_rejects_missing_course_data_section():
    bad_mrc = """
[COURSE HEADER]
VERSION = 2
MINUTES PERCENT
[END COURSE HEADER]
""".strip()

    with pytest.raises(MRCParseError, match=r"Missing \[COURSE DATA\] section"):
        parse_mrc_text(bad_mrc, ftp_watts=250)


def test_parse_mrc_rejects_non_numeric_columns():
    bad_mrc = """
[COURSE DATA]
0.0 fifty
5.0 60
[END COURSE DATA]
""".strip()

    with pytest.raises(MRCParseError, match="invalid PERCENT value"):
        parse_mrc_text(bad_mrc, ftp_watts=250)


def test_parse_mrc_rejects_decreasing_minutes():
    bad_mrc = """
[COURSE DATA]
0.0 50
5.0 60
4.0 70
[END COURSE DATA]
""".strip()

    with pytest.raises(MRCParseError, match="MINUTES must be non-decreasing"):
        parse_mrc_text(bad_mrc, ftp_watts=250)


def test_parse_mrc_rejects_invalid_ftp():
    mrc_text = """
[COURSE DATA]
0.0 50
5.0 60
[END COURSE DATA]
""".strip()

    with pytest.raises(MRCParseError, match="FTP must be a positive integer"):
        parse_mrc_text(mrc_text, ftp_watts=0)


# ── parse_mrc_header ──────────────────────────────────────────────────────────

def test_parse_mrc_header_returns_category_value():
    mrc = """
[COURSE HEADER]
VERSION = 2
CATEGORY = SST
[END COURSE HEADER]
[COURSE DATA]
0.0 50
5.0 50
[END COURSE DATA]
""".strip()
    header = parse_mrc_header(mrc)
    assert header.get("category") == "SST"


def test_parse_mrc_header_missing_category_returns_empty_via_get():
    mrc = """
[COURSE HEADER]
VERSION = 2
[END COURSE HEADER]
[COURSE DATA]
0.0 50
5.0 50
[END COURSE DATA]
""".strip()
    header = parse_mrc_header(mrc)
    assert header.get("category", "") == ""


def test_parse_mrc_header_no_header_section_returns_empty_dict():
    mrc = """
[COURSE DATA]
0.0 50
5.0 50
[END COURSE DATA]
""".strip()
    header = parse_mrc_header(mrc)
    assert header == {}


def test_parse_mrc_header_reads_from_file(tmp_path):
    mrc_file = tmp_path / "workout.mrc"
    mrc_file.write_text(
        "[COURSE HEADER]\nCATEGORY = Threshold\n[END COURSE HEADER]\n"
        "[COURSE DATA]\n0.0 50\n5.0 50\n[END COURSE DATA]\n",
        encoding="utf-8",
    )
    header = parse_mrc_header(mrc_file)
    assert header.get("category") == "Threshold"


# ── inject_category_into_mrc_text ─────────────────────────────────────────────

_HEADER_MRC = """[COURSE HEADER]
VERSION = 2
[END COURSE HEADER]
[COURSE DATA]
0.0 50
5.0 50
[END COURSE DATA]"""

_HEADER_WITH_CAT_MRC = """[COURSE HEADER]
VERSION = 2
CATEGORY = OldCat
[END COURSE HEADER]
[COURSE DATA]
0.0 50
5.0 50
[END COURSE DATA]"""


def test_inject_category_adds_new_line():
    result = inject_category_into_mrc_text(_HEADER_MRC, "SST")
    assert "CATEGORY = SST" in result
    assert "[END COURSE HEADER]" in result


def test_inject_category_replaces_existing():
    result = inject_category_into_mrc_text(_HEADER_WITH_CAT_MRC, "Threshold")
    assert "CATEGORY = Threshold" in result
    assert "CATEGORY = OldCat" not in result
    assert result.count("CATEGORY") == 1


def test_inject_category_roundtrips_through_parse():
    result = inject_category_into_mrc_text(_HEADER_MRC, "VO2max")
    header = parse_mrc_header(result)
    assert header.get("category") == "VO2max"


# ── Prepackaged MRC files: category headers ───────────────────────────────────

_WORKOUTS_DIR = Path(__file__).parent.parent.parent / "workouts"

_PACKAGED_CATEGORIES = [
    ("Z2_65_30m.mrc",          "Z2"),
    ("Z2_65_60m.mrc",          "Z2"),
    ("LT1_72_45m.mrc",         "LT1"),
    ("Z3_85_2x20.mrc",         "Tempo"),
    ("Z3_85_1x30.mrc",         "Tempo"),
    ("SST_90_2x20.mrc",        "SST"),
    ("SST_90_4x8.mrc",         "SST"),
    ("SST_90_3x15.mrc",        "SST"),
    ("SST_90_2x25.mrc",        "SST"),
    ("Z4_95_3x10.mrc",         "Threshold"),
    ("Z4_95_2x20.mrc",         "Threshold"),
    ("Z4_95_4x10.mrc",         "Threshold"),
    ("KM_Baseline_FTP_Test.mrc", "Test"),
    ("VO2_2x3_120-120.mrc",    "VO2max"),
    ("VO2_3x6_60-60.mrc",      "VO2max"),
    ("VO2_3x12_30-30.mrc",     "VO2max"),
]


@pytest.mark.parametrize("filename,expected_category", _PACKAGED_CATEGORIES)
def test_packaged_mrc_has_correct_category(filename: str, expected_category: str):
    path = _WORKOUTS_DIR / filename
    header = parse_mrc_header(path)
    assert header.get("category") == expected_category, (
        f"{filename}: expected category '{expected_category}', got '{header.get('category')}'"
    )


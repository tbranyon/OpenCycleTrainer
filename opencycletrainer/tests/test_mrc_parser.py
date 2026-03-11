from __future__ import annotations

from pathlib import Path

import pytest

from opencycletrainer.core.mrc_parser import MRCParseError, parse_mrc_file, parse_mrc_text


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


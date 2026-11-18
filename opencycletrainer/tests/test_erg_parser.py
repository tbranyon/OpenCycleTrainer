"""Parsing ERG workouts, whose targets are written in watts."""

from __future__ import annotations

from pathlib import Path

import pytest

from opencycletrainer.core.erg_parser import ERGParseError, parse_erg_file, parse_erg_text

TEST_DATA_DIR = Path(__file__).parent / "data"


def _erg(rows: str, *, header: str = "") -> str:
    return (
        "[COURSE HEADER]\nVERSION = 2\nUNITS = ENGLISH\n"
        f"{header}"
        "MINUTES WATTS\n[END COURSE HEADER]\n"
        f"[COURSE DATA]\n{rows}[END COURSE DATA]\n"
    )


def test_without_an_ftp_line_targets_are_the_watts_written():
    text = _erg("0 100\n5 100\n5 200\n10 250\n")

    workout = parse_erg_text(text, ftp_watts=250)

    assert [iv.duration_seconds for iv in workout.intervals] == [300, 300]
    assert [(iv.start_target_watts, iv.end_target_watts) for iv in workout.intervals] == [(100, 100), (200, 250)]
    assert [(iv.start_percent_ftp, iv.end_percent_ftp) for iv in workout.intervals] == [
        pytest.approx((40.0, 40.0)),
        pytest.approx((80.0, 100.0)),
    ]


def test_an_ftp_line_scales_targets_to_the_riders_ftp():
    text = _erg("0 100\n10 200\n", header="FTP = 200\n")

    workout = parse_erg_text(text, ftp_watts=300)

    (interval,) = workout.intervals
    assert (interval.start_target_watts, interval.end_target_watts) == (150, 300)
    assert (interval.start_percent_ftp, interval.end_percent_ftp) == pytest.approx((50.0, 100.0))


def test_a_file_is_named_from_its_description():
    workout = parse_erg_file(TEST_DATA_DIR / "steady.erg", ftp_watts=250)

    assert workout.name == "Steady Watts"
    assert workout.total_duration_seconds == 300


def test_a_file_without_a_description_is_named_after_the_file(tmp_path):
    path = tmp_path / "Tempo Block.erg"
    path.write_text(_erg("0 180\n20 180\n"), encoding="utf-8")

    assert parse_erg_file(path, ftp_watts=250).name == "Tempo Block"


@pytest.mark.parametrize(
    ("text", "ftp_watts"),
    [
        ("[COURSE HEADER]\nMINUTES WATTS\n[END COURSE HEADER]\n", 250),
        (_erg("0 100\n5 lots\n"), 250),
        (_erg("0 100\n5 100\n4 120\n"), 250),
        (_erg("0 100\n"), 250),
        (_erg("0 100\n5 100\n", header="FTP = abc\n"), 250),
        (_erg("0 100\n5 100\n", header="FTP = 0\n"), 250),
        (_erg("0 100\n5 100\n"), 0),
    ],
    ids=[
        "missing-course-data",
        "non-numeric-watts",
        "decreasing-minutes",
        "single-point",
        "non-numeric-ftp-line",
        "zero-ftp-line",
        "zero-rider-ftp",
    ],
)
def test_invalid_erg_is_rejected(text, ftp_watts):
    with pytest.raises(ERGParseError):
        parse_erg_text(text, ftp_watts=ftp_watts)

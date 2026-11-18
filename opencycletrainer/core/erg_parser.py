"""Parse ERG workouts: MRC-style files whose targets are written in watts."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from pathlib import Path

from .mrc_parser import build_course_intervals, course_workout_name, read_course_text
from .workout_model import Workout

_FTP_HEADER_KEY = "ftp"
_PERCENT_SCALE = Decimal(100)


class ERGParseError(ValueError):
    """Raised when an ERG file cannot be parsed."""


def parse_erg_file(path: str | Path, ftp_watts: int) -> Workout:
    """Parse an ERG file from disk and return a Workout."""
    source_path = Path(path)
    text = source_path.read_text(encoding="utf-8")
    return parse_erg_text(text, ftp_watts=ftp_watts, fallback_workout_name=source_path.stem)


def parse_erg_text(
    text: str,
    ftp_watts: int,
    fallback_workout_name: str = "Workout",
) -> Workout:
    """Parse ERG text and return a Workout for a rider with *ftp_watts*.

    When the header gives the FTP the file was written for, each target is taken as
    a share of that FTP and applied to the rider's, as MRC and ZWO targets are.
    Otherwise the targets are ridden as the watts written.
    """
    if ftp_watts <= 0:
        raise ERGParseError("FTP must be a positive integer.")

    header, points = read_course_text(text, ERGParseError, file_kind="ERG", value_column="WATTS")
    reference_ftp = _header_ftp(header) or Decimal(ftp_watts)
    percent_points = [
        (minutes, watts * _PERCENT_SCALE / reference_ftp, line_number)
        for minutes, watts, line_number in points
    ]
    intervals = build_course_intervals(percent_points, ftp_watts=ftp_watts, error=ERGParseError)
    if not intervals:
        raise ERGParseError("ERG file did not produce any intervals.")

    return Workout(
        name=course_workout_name(header, fallback_workout_name),
        ftp_watts=ftp_watts,
        intervals=tuple(intervals),
    )


def _header_ftp(header: dict[str, str]) -> Decimal | None:
    """Return the FTP the file was written for, or None when the header has none."""
    raw = header.get(_FTP_HEADER_KEY)
    if raw is None or not raw.strip():
        return None
    try:
        value = Decimal(raw.strip())
    except InvalidOperation as exc:
        raise ERGParseError(f"Invalid FTP value '{raw}' in the course header.") from exc
    if not value.is_finite() or value <= 0:
        raise ERGParseError(f"FTP in the course header must be positive, got '{raw}'.")
    return value

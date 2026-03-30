from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Iterable

from .workout_model import Workout, WorkoutInterval


class MRCParseError(ValueError):
    """Raised when an MRC file cannot be parsed."""


def parse_mrc_header(path_or_text: str | Path) -> dict[str, str]:
    """Return the [COURSE HEADER] key-value pairs as a lowercase-keyed dict.

    Accepts either a file path or raw MRC text.
    """
    if isinstance(path_or_text, Path) or (
        isinstance(path_or_text, str) and not path_or_text.lstrip().startswith("[")
        and Path(path_or_text).exists()
    ):
        text = Path(path_or_text).read_text(encoding="utf-8")
    else:
        text = str(path_or_text)

    result: dict[str, str] = {}
    in_header = False
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        lowered = stripped.lower()
        if lowered == "[course header]":
            in_header = True
            continue
        if lowered == "[end course header]":
            break
        if in_header and "=" in stripped:
            key, value = stripped.split("=", 1)
            result[key.strip().lower()] = value.strip()
    return result


def inject_category_into_mrc_text(text: str, category: str) -> str:
    """Insert or replace a CATEGORY line in [COURSE HEADER].

    If CATEGORY already exists, replace it. Otherwise insert it before
    [END COURSE HEADER]. Returns modified text.
    """
    lines = text.splitlines(keepends=True)
    new_lines: list[str] = []
    injected = False

    for line in lines:
        stripped = line.strip()
        if stripped.upper().startswith("CATEGORY") and "=" in stripped:
            new_lines.append(f"CATEGORY = {category}\n")
            injected = True
            continue
        if stripped.upper() == "[END COURSE HEADER]" and not injected:
            new_lines.append(f"CATEGORY = {category}\n")
            injected = True
        new_lines.append(line)

    return "".join(new_lines)


def parse_mrc_file(path: str | Path, ftp_watts: int) -> Workout:
    source_path = Path(path)
    text = source_path.read_text(encoding="utf-8")
    return parse_mrc_text(text, ftp_watts=ftp_watts, fallback_workout_name=source_path.stem)


def parse_mrc_text(
    text: str,
    ftp_watts: int,
    fallback_workout_name: str = "Workout",
) -> Workout:
    if ftp_watts <= 0:
        raise MRCParseError("FTP must be a positive integer.")

    header: dict[str, str] = {}
    points: list[tuple[Decimal, Decimal, int]] = []
    in_course_data = False
    saw_course_data_section = False

    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        stripped = raw_line.strip()
        if not stripped or stripped.startswith(";"):
            continue

        lowered = stripped.lower()
        if lowered == "[course data]":
            in_course_data = True
            saw_course_data_section = True
            continue
        if lowered == "[end course data]":
            in_course_data = False
            continue

        if in_course_data:
            minute_value, percent_value = _parse_data_row(stripped, line_number)
            points.append((minute_value, percent_value, line_number))
            continue

        if "=" in stripped:
            key, value = stripped.split("=", 1)
            header[key.strip().lower()] = value.strip()

    if not saw_course_data_section:
        raise MRCParseError("Missing [COURSE DATA] section.")
    if len(points) < 2:
        raise MRCParseError("MRC file must define at least two course data points.")

    intervals = _build_intervals(points, ftp_watts=ftp_watts)
    if not intervals:
        raise MRCParseError("MRC file did not produce any intervals.")

    workout_name = (
        header.get("description")
        or header.get("workoutname")
        or header.get("file name")
        or fallback_workout_name
    ).strip()

    return Workout(name=workout_name or "Workout", ftp_watts=ftp_watts, intervals=tuple(intervals))


def _parse_data_row(row: str, line_number: int) -> tuple[Decimal, Decimal]:
    fields = row.split()
    if len(fields) < 2:
        raise MRCParseError(
            f"Line {line_number}: expected two numeric columns (MINUTES PERCENT), got '{row}'."
        )

    minute_value = _parse_decimal(fields[0], line_number=line_number, field_name="MINUTES")
    percent_value = _parse_decimal(fields[1], line_number=line_number, field_name="PERCENT")

    if minute_value < 0:
        raise MRCParseError(f"Line {line_number}: MINUTES must be >= 0.")
    if percent_value < 0:
        raise MRCParseError(f"Line {line_number}: PERCENT must be >= 0.")

    return minute_value, percent_value


def _parse_decimal(value: str, line_number: int, field_name: str) -> Decimal:
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise MRCParseError(
            f"Line {line_number}: invalid {field_name} value '{value}'."
        ) from exc


def _build_intervals(
    points: Iterable[tuple[Decimal, Decimal, int]],
    ftp_watts: int,
) -> list[WorkoutInterval]:
    point_list = list(points)
    intervals: list[WorkoutInterval] = []

    for index in range(1, len(point_list)):
        prev_minute, prev_percent, prev_line = point_list[index - 1]
        curr_minute, curr_percent, curr_line = point_list[index]

        if curr_minute < prev_minute:
            raise MRCParseError(
                "Line "
                f"{curr_line}: MINUTES must be non-decreasing (previous value on line {prev_line})."
            )

        delta_minutes = curr_minute - prev_minute
        if delta_minutes == 0:
            # Same-timestamp points represent an instantaneous step change.
            continue

        duration_seconds = int(
            (delta_minutes * Decimal("60")).to_integral_value(rounding=ROUND_HALF_UP)
        )
        if duration_seconds <= 0:
            raise MRCParseError(
                f"Line {curr_line}: interval duration is too short after rounding."
            )

        interval = WorkoutInterval(
            start_offset_seconds=int(
                (prev_minute * Decimal("60")).to_integral_value(rounding=ROUND_HALF_UP)
            ),
            duration_seconds=duration_seconds,
            start_percent_ftp=float(prev_percent),
            end_percent_ftp=float(curr_percent),
            start_target_watts=_percent_to_watts(prev_percent, ftp_watts=ftp_watts),
            end_target_watts=_percent_to_watts(curr_percent, ftp_watts=ftp_watts),
        )
        intervals.append(interval)

    return intervals


def _percent_to_watts(percent: Decimal, ftp_watts: int) -> int:
    return int((Decimal(ftp_watts) * percent / Decimal("100")).to_integral_value(rounding=ROUND_HALF_UP))


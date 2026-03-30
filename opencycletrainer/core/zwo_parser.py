from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from .workout_model import Workout, WorkoutInterval


class ZWOParseError(ValueError):
    """Raised when a ZWO file cannot be parsed."""


# ── Public API ────────────────────────────────────────────────────────────────

def parse_zwo_file(path: str | Path, ftp_watts: int) -> Workout:
    """Parse a ZWO file from disk and return a Workout."""
    source_path = Path(path)
    text = source_path.read_text(encoding="utf-8")
    return parse_zwo_text(text, ftp_watts=ftp_watts, fallback_workout_name=source_path.stem)


def parse_zwo_text(
    text: str,
    ftp_watts: int,
    fallback_workout_name: str = "Workout",
) -> Workout:
    """Parse ZWO XML text and return a Workout."""
    if ftp_watts <= 0:
        raise ZWOParseError("FTP must be a positive integer.")

    root = _parse_xml(text)

    workout_el = root.find("workout")
    if workout_el is None:
        raise ZWOParseError("Missing <workout> element in ZWO file.")

    name_el = root.find("name")
    raw_name = (name_el.text or "").strip() if name_el is not None else ""
    workout_name = raw_name or fallback_workout_name or "Workout"

    intervals = _build_intervals(workout_el, ftp_watts)
    if not intervals:
        raise ZWOParseError("ZWO file did not produce any intervals.")

    return Workout(name=workout_name, ftp_watts=ftp_watts, intervals=tuple(intervals))


def parse_zwo_header(path_or_text: str | Path) -> dict[str, str]:
    """Return a dict with keys: name, description, sportType, category.

    Accepts either a file path or raw ZWO XML text.
    """
    if isinstance(path_or_text, Path) or (
        isinstance(path_or_text, str)
        and not path_or_text.lstrip().startswith("<")
        and Path(path_or_text).exists()
    ):
        text = Path(path_or_text).read_text(encoding="utf-8")
    else:
        text = str(path_or_text)

    root = _parse_xml(text)

    def _text(tag: str) -> str:
        el = root.find(tag)
        return (el.text or "").strip() if el is not None else ""

    return {
        "name": _text("name"),
        "description": _text("description"),
        "sportType": _text("sportType"),
        "category": _text("oct_category"),
    }


def inject_category_into_zwo_text(text: str, category: str) -> str:
    """Insert or replace <oct_category> as a child of <workout_file>.

    If an <oct_category> element already exists, replaces its text content.
    Returns the modified XML as a string.
    """
    root = _parse_xml(text)

    existing = root.find("oct_category")
    if existing is not None:
        existing.text = category
    else:
        el = ET.SubElement(root, "oct_category")
        el.text = category

    return ET.tostring(root, encoding="unicode", xml_declaration=False)


# ── XML helpers ───────────────────────────────────────────────────────────────

def _parse_xml(text: str) -> ET.Element:
    try:
        return ET.fromstring(text)
    except ET.ParseError as exc:
        raise ZWOParseError(f"XML parse error: {exc}") from exc


def _get_float_attr(element: ET.Element, attr: str) -> float:
    """Return a float attribute value, raising ZWOParseError on failure."""
    value = element.get(attr)
    if value is None:
        raise ZWOParseError(
            f"<{element.tag}> is missing required attribute '{attr}'."
        )
    try:
        return float(value)
    except ValueError as exc:
        raise ZWOParseError(
            f"<{element.tag}> attribute '{attr}' is not a valid number: '{value}'."
        ) from exc


def _get_int_attr(element: ET.Element, attr: str) -> int:
    """Return an int attribute value, raising ZWOParseError on failure."""
    value = element.get(attr)
    if value is None:
        raise ZWOParseError(
            f"<{element.tag}> is missing required attribute '{attr}'."
        )
    try:
        return int(float(value))
    except ValueError as exc:
        raise ZWOParseError(
            f"<{element.tag}> attribute '{attr}' is not a valid number: '{value}'."
        ) from exc


def _fraction_to_percent(fraction: float) -> float:
    return fraction * 100.0


def _fraction_to_watts(fraction: float, ftp_watts: int) -> int:
    return round(ftp_watts * fraction)


# ── Interval building ─────────────────────────────────────────────────────────

_RAMP_TAGS = {"Warmup", "Cooldown", "Ramp"}
_FREE_RIDE_TAGS = {"FreeRide", "MaxEffort"}
_KNOWN_TAGS = {"SteadyState"} | _RAMP_TAGS | _FREE_RIDE_TAGS | {"IntervalsT"}


def _build_intervals(
    workout_el: ET.Element,
    ftp_watts: int,
) -> list[WorkoutInterval]:
    """Convert all child elements of <workout> into WorkoutInterval objects."""
    intervals: list[WorkoutInterval] = []
    current_offset = 0

    for element in workout_el:
        tag = element.tag
        if tag not in _KNOWN_TAGS:
            continue

        if tag == "SteadyState":
            iv = _parse_steady_state(element, ftp_watts, current_offset)
            intervals.append(iv)
            current_offset += iv.duration_seconds

        elif tag in _RAMP_TAGS:
            iv = _parse_ramp(element, ftp_watts, current_offset)
            intervals.append(iv)
            current_offset += iv.duration_seconds

        elif tag in _FREE_RIDE_TAGS:
            iv = _parse_free_ride(element, current_offset)
            intervals.append(iv)
            current_offset += iv.duration_seconds

        elif tag == "IntervalsT":
            new_intervals = _parse_intervals_t(element, ftp_watts, current_offset)
            intervals.extend(new_intervals)
            current_offset += sum(iv.duration_seconds for iv in new_intervals)

    return intervals


def _parse_steady_state(
    element: ET.Element,
    ftp_watts: int,
    offset: int,
) -> WorkoutInterval:
    duration = _get_int_attr(element, "Duration")
    power = _get_float_attr(element, "Power")
    pct = _fraction_to_percent(power)
    watts = _fraction_to_watts(power, ftp_watts)
    return WorkoutInterval(
        start_offset_seconds=offset,
        duration_seconds=duration,
        start_percent_ftp=pct,
        end_percent_ftp=pct,
        start_target_watts=watts,
        end_target_watts=watts,
    )


def _parse_ramp(
    element: ET.Element,
    ftp_watts: int,
    offset: int,
) -> WorkoutInterval:
    duration = _get_int_attr(element, "Duration")
    power_low = _get_float_attr(element, "PowerLow")
    power_high = _get_float_attr(element, "PowerHigh")
    return WorkoutInterval(
        start_offset_seconds=offset,
        duration_seconds=duration,
        start_percent_ftp=_fraction_to_percent(power_low),
        end_percent_ftp=_fraction_to_percent(power_high),
        start_target_watts=_fraction_to_watts(power_low, ftp_watts),
        end_target_watts=_fraction_to_watts(power_high, ftp_watts),
    )


def _parse_free_ride(element: ET.Element, offset: int) -> WorkoutInterval:
    duration = _get_int_attr(element, "Duration")
    return WorkoutInterval(
        start_offset_seconds=offset,
        duration_seconds=duration,
        start_percent_ftp=0.0,
        end_percent_ftp=0.0,
        start_target_watts=0,
        end_target_watts=0,
        free_ride=True,
    )


def _parse_intervals_t(
    element: ET.Element,
    ftp_watts: int,
    offset: int,
) -> list[WorkoutInterval]:
    repeat = _get_int_attr(element, "Repeat")
    on_duration = _get_int_attr(element, "OnDuration")
    off_duration = _get_int_attr(element, "OffDuration")
    on_power = _get_float_attr(element, "OnPower")
    off_power = _get_float_attr(element, "OffPower")

    on_pct = _fraction_to_percent(on_power)
    off_pct = _fraction_to_percent(off_power)
    on_watts = _fraction_to_watts(on_power, ftp_watts)
    off_watts = _fraction_to_watts(off_power, ftp_watts)

    intervals: list[WorkoutInterval] = []
    current = offset
    for _ in range(repeat):
        intervals.append(WorkoutInterval(
            start_offset_seconds=current,
            duration_seconds=on_duration,
            start_percent_ftp=on_pct,
            end_percent_ftp=on_pct,
            start_target_watts=on_watts,
            end_target_watts=on_watts,
        ))
        current += on_duration
        intervals.append(WorkoutInterval(
            start_offset_seconds=current,
            duration_seconds=off_duration,
            start_percent_ftp=off_pct,
            end_percent_ftp=off_pct,
            start_target_watts=off_watts,
            end_target_watts=off_watts,
        ))
        current += off_duration
    return intervals

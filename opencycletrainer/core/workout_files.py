"""Read workout files of every supported format, chosen by file extension."""

from __future__ import annotations

from pathlib import Path

from .erg_parser import ERGParseError, parse_erg_file
from .mrc_parser import MRCParseError, parse_mrc_file, parse_mrc_header
from .workout_model import Workout
from .zwo_parser import ZWOParseError, parse_zwo_file, parse_zwo_header

MRC_FILE_SUFFIX = ".mrc"
ZWO_FILE_SUFFIX = ".zwo"
ERG_FILE_SUFFIX = ".erg"
WORKOUT_FILE_SUFFIXES = (MRC_FILE_SUFFIX, ZWO_FILE_SUFFIX, ERG_FILE_SUFFIX)
WORKOUT_PARSE_ERRORS = (MRCParseError, ZWOParseError, ERGParseError)


def workout_file_filter(label: str = "Workout Files") -> str:
    """Return a file dialog filter listing every supported workout extension."""
    patterns = " ".join(f"*{suffix}" for suffix in WORKOUT_FILE_SUFFIXES)
    return f"{label} ({patterns})"


def parse_workout_file(path: Path, ftp_watts: int) -> Workout:
    """Parse a .mrc, .zwo or .erg workout for a rider with *ftp_watts*.

    Raises one of WORKOUT_PARSE_ERRORS for an invalid file, or OSError if it can't be read.
    """
    suffix = path.suffix.lower()
    if suffix == ZWO_FILE_SUFFIX:
        return parse_zwo_file(path, ftp_watts=ftp_watts)
    if suffix == ERG_FILE_SUFFIX:
        return parse_erg_file(path, ftp_watts=ftp_watts)
    return parse_mrc_file(path, ftp_watts=ftp_watts)


def parse_workout_header(path: Path) -> dict[str, str]:
    """Return a workout file's header fields; a category, if any, is under "category"."""
    if path.suffix.lower() == ZWO_FILE_SUFFIX:
        return parse_zwo_header(path)
    return parse_mrc_header(path)

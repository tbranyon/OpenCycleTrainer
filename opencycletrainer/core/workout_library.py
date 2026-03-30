from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

from opencycletrainer.core.mrc_parser import MRCParseError, parse_mrc_file, parse_mrc_header
from opencycletrainer.core.zwo_parser import ZWOParseError, parse_zwo_file, parse_zwo_header
from opencycletrainer.storage.paths import get_prepackaged_workouts_dir, get_user_workouts_dir

_logger = logging.getLogger(__name__)

_DUMMY_FTP = 200  # Arbitrary FTP used for duration-only parsing


@dataclass
class WorkoutLibraryEntry:
    """A single workout entry in the library."""

    name: str
    path: Path
    duration_seconds: int
    category: str = ""


class WorkoutLibrary:
    """Scans user and prepackaged workout directories and exposes their entries."""

    def __init__(
        self,
        user_dir: Path | None = None,
        prepackaged_dir: Path | None = None,
    ) -> None:
        self._user_dir = user_dir if user_dir is not None else get_user_workouts_dir()
        self._prepackaged_dir = (
            prepackaged_dir if prepackaged_dir is not None else get_prepackaged_workouts_dir()
        )
        self.entries: list[WorkoutLibraryEntry] = []
        self.refresh()

    def refresh(self) -> None:
        """Rescan both directories and rebuild the entries list."""
        entries: list[WorkoutLibraryEntry] = []
        for source_dir in (self._user_dir, self._prepackaged_dir):
            if not source_dir.exists():
                continue
            paths = sorted(source_dir.glob("*.mrc")) + sorted(source_dir.glob("*.zwo"))
            for path in sorted(paths):
                entry = self._try_parse(path)
                if entry is not None:
                    entries.append(entry)
        self.entries = entries

    def add_workout(self, source_path: Path) -> WorkoutLibraryEntry:
        """Copy *source_path* into the user workouts directory and return its entry."""
        dest = self._user_dir / source_path.name
        shutil.copy2(source_path, dest)
        self.refresh()
        for entry in self.entries:
            if entry.path == dest:
                return entry
        raise RuntimeError(f"Added workout not found after refresh: {dest}")

    def add_workout_from_text(self, text: str, filename: str) -> WorkoutLibraryEntry:
        """Write MRC text directly to user workouts dir and return the entry."""
        dest = self._user_dir / filename
        dest.write_text(text, encoding="utf-8")
        self.refresh()
        for entry in self.entries:
            if entry.path == dest:
                return entry
        raise RuntimeError(f"Added workout not found after refresh: {dest}")

    def _try_parse(self, path: Path) -> WorkoutLibraryEntry | None:
        try:
            if path.suffix.lower() == ".zwo":
                workout = parse_zwo_file(path, ftp_watts=_DUMMY_FTP)
                header = parse_zwo_header(path)
            else:
                workout = parse_mrc_file(path, ftp_watts=_DUMMY_FTP)
                header = parse_mrc_header(path)
        except (ZWOParseError, MRCParseError, OSError, UnicodeDecodeError):
            _logger.warning("Skipping unparseable workout file: %s", path)
            return None
        return WorkoutLibraryEntry(
            name=path.stem,
            path=path,
            duration_seconds=workout.total_duration_seconds,
            category=header.get("category", ""),
        )

from __future__ import annotations

from opencycletrainer.core.workout_model import Workout


def workout_to_mrc_text(workout: Workout, category: str = "") -> str:
    """Convert a Workout to MRC (MINUTES PERCENT) format text.

    start_percent_ftp / end_percent_ftp are stored on the interval in 0-100 scale
    (e.g. 110.0 for 110 % FTP), which maps directly to the MRC PERCENT column.

    Adjacent intervals with different power at their shared boundary produce
    duplicate time entries in the output, which the MRC parser treats as
    instantaneous step changes (zero-duration segments are skipped on re-parse).
    """
    lines: list[str] = [
        "[COURSE HEADER]",
        "VERSION = 2",
        "UNITS = ENGLISH",
        f"DESCRIPTION = {workout.name}",
    ]
    if category:
        lines.append(f"CATEGORY = {category}")
    lines += [
        "MINUTES PERCENT",
        "[END COURSE HEADER]",
        "[COURSE DATA]",
    ]

    points: list[tuple[float, float]] = []
    for iv in workout.intervals:
        t_start = iv.start_offset_seconds / 60.0
        t_end = iv.end_offset_seconds / 60.0
        points.append((t_start, iv.start_percent_ftp))
        points.append((t_end, iv.end_percent_ftp))

    # Remove consecutive identical points so the file stays clean.
    deduped: list[tuple[float, float]] = []
    for pt in points:
        if not deduped or deduped[-1] != pt:
            deduped.append(pt)

    for t, pct in deduped:
        lines.append(f"{t:.4f}\t{pct:.2f}")

    lines += ["[END COURSE DATA]", ""]
    return "\n".join(lines)

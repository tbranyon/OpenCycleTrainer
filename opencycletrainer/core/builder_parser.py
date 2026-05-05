from __future__ import annotations

import re

from opencycletrainer.core.workout_model import Workout, WorkoutInterval

_DUR_RE = re.compile(r"^(\d+(?:\.\d+)?)(m|s)$", re.IGNORECASE)
_PCT_RE = re.compile(r"^(\d+(?:\.\d+)?)%$")
_WATTS_RE = re.compile(r"^(\d+(?:\.\d+)?)w$", re.IGNORECASE)
_RAMP_PCT_RE = re.compile(r"^ramp\s+(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)%$", re.IGNORECASE)
_RAMP_WATTS_RE = re.compile(r"^ramp\s+(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)w$", re.IGNORECASE)
_FREE_RE = re.compile(r"^free(?:ride)?$", re.IGNORECASE)
_REPEAT_RE = re.compile(r"^(\d+)x\((.+)\)(!?)$", re.IGNORECASE)

# (duration_s, start_pct_0to100, end_pct_0to100, start_watts, end_watts, free_ride)
_Step = tuple[int, float, float, int, int, bool]


def _parse_duration(token: str) -> int | None:
    m = _DUR_RE.match(token)
    if not m:
        return None
    value = float(m.group(1))
    if m.group(2).lower() == "m":
        return max(1, int(round(value * 60)))
    return max(1, int(round(value)))


def _parse_step(text: str, ftp_watts: int) -> _Step | str:
    """Parse a single step like '5m 110%' or '10m ramp 60-90%'.

    Returns a _Step tuple on success or an error string on failure.
    Percent values stored in 0-100 scale (e.g. 110.0 for 110 % FTP).
    """
    tokens = text.strip().split()
    if not tokens:
        return "empty step"

    dur = _parse_duration(tokens[0])
    if dur is None:
        return f"invalid duration {tokens[0]!r}"

    spec = " ".join(tokens[1:]).strip()
    if not spec:
        return "missing power specification"

    if _FREE_RE.match(spec):
        return dur, 0.0, 0.0, 0, 0, True

    m = _PCT_RE.match(spec)
    if m:
        pct = float(m.group(1))
        w = max(0, round(pct * ftp_watts / 100))
        return dur, pct, pct, w, w, False

    m = _WATTS_RE.match(spec)
    if m:
        w = max(0, round(float(m.group(1))))
        pct = w / ftp_watts * 100.0 if ftp_watts > 0 else 0.0
        return dur, pct, pct, w, w, False

    m = _RAMP_PCT_RE.match(spec)
    if m:
        pct_s, pct_e = float(m.group(1)), float(m.group(2))
        w_s = max(0, round(pct_s * ftp_watts / 100))
        w_e = max(0, round(pct_e * ftp_watts / 100))
        return dur, pct_s, pct_e, w_s, w_e, False

    m = _RAMP_WATTS_RE.match(spec)
    if m:
        w_s = max(0, round(float(m.group(1))))
        w_e = max(0, round(float(m.group(2))))
        pct_s = w_s / ftp_watts * 100.0 if ftp_watts > 0 else 0.0
        pct_e = w_e / ftp_watts * 100.0 if ftp_watts > 0 else 0.0
        return dur, pct_s, pct_e, w_s, w_e, False

    return f"unrecognized power specification {spec!r}"


def parse_builder_text(
    text: str,
    ftp_watts: int,
    name: str,
) -> tuple[Workout, list[str]]:
    """Parse builder syntax into a Workout.

    Lines starting with '-' are steps; '#' lines and blank lines are ignored.
    Returns (Workout, error_list). Errors are non-fatal — valid steps still
    produce intervals so the preview graph reflects partial input.
    """
    errors: list[str] = []
    steps: list[_Step] = []

    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue

        if not line.startswith("-"):
            errors.append(f"Line {lineno}: expected '-' at start of step")
            continue

        body = line[1:].strip()

        m = _REPEAT_RE.match(body)
        if m:
            count = int(m.group(1))
            omit_trailing = bool(m.group(3))
            sub_steps: list[_Step] = []
            ok = True
            for sub in (s.strip() for s in m.group(2).split(",")):
                result = _parse_step(sub, ftp_watts)
                if isinstance(result, str):
                    errors.append(f"Line {lineno}: {result}")
                    ok = False
                else:
                    sub_steps.append(result)
            if ok and sub_steps:
                expanded = sub_steps * count
                if omit_trailing and expanded:
                    expanded = expanded[:-1]
                steps.extend(expanded)
            continue

        result = _parse_step(body, ftp_watts)
        if isinstance(result, str):
            errors.append(f"Line {lineno}: {result}")
        else:
            steps.append(result)

    intervals: list[WorkoutInterval] = []
    offset = 0
    for dur, sp, ep, sw, ew, fr in steps:
        intervals.append(
            WorkoutInterval(
                start_offset_seconds=offset,
                duration_seconds=dur,
                start_percent_ftp=sp,
                end_percent_ftp=ep,
                start_target_watts=sw,
                end_target_watts=ew,
                free_ride=fr,
            )
        )
        offset += dur

    return (
        Workout(
            name=name or "Untitled",
            ftp_watts=max(1, ftp_watts),
            intervals=tuple(intervals),
        ),
        errors,
    )

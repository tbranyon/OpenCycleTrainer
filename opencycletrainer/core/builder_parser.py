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
_BLOCK_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _-]*$")
_BLOCK_REF_RE = re.compile(r"^@([A-Za-z0-9][A-Za-z0-9 _-]*)$")

# (duration_s, start_pct_0to100, end_pct_0to100, start_watts, end_watts, free_ride)
_Step = tuple[int, float, float, int, int, bool]


def is_valid_block_name(name: str) -> bool:
    """Return True if name is a valid reusable-block identifier."""
    return bool(_BLOCK_NAME_RE.match(name))


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


def _collect_steps(
    text: str,
    ftp_watts: int,
    blocks: dict[str, str] | None,
) -> tuple[list[_Step], list[str]]:
    """Collect raw steps from builder text, expanding repeats and block refs.

    Lines starting with '-' are steps; '#' lines and blank lines are ignored.
    When blocks is None, '@name' references are rejected — this is how nesting
    is prevented (block bodies are collected with blocks=None). Errors are
    non-fatal: valid lines still contribute steps.
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

        m = _BLOCK_REF_RE.match(body)
        if m:
            block_name = m.group(1)
            if blocks is None:
                errors.append(
                    f"Line {lineno}: block references not allowed inside a block"
                )
            elif block_name not in blocks:
                errors.append(f"Line {lineno}: unknown block {block_name!r}")
            else:
                sub_steps, sub_errs = _collect_steps(blocks[block_name], ftp_watts, None)
                errors.extend(f"Line {lineno} ({block_name}): {e}" for e in sub_errs)
                steps.extend(sub_steps)
            continue

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

    return steps, errors


def parse_builder_text(
    text: str,
    ftp_watts: int,
    name: str,
    blocks: dict[str, str] | None = None,
) -> tuple[Workout, list[str]]:
    """Parse builder syntax into a Workout.

    Lines starting with '-' are steps; '#' lines and blank lines are ignored.
    A '- @name' line expands the named reusable block from blocks (re-parsed at
    the current FTP). Returns (Workout, error_list). Errors are non-fatal —
    valid steps still produce intervals so the preview graph reflects partial
    input.
    """
    steps, errors = _collect_steps(text, ftp_watts, blocks or {})

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


def _format_duration_token(seconds: int) -> str:
    if seconds > 0 and seconds % 60 == 0:
        return f"{seconds // 60}m"
    return f"{seconds}s"


def _format_pct_token(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    return f"{value:g}"


def workout_to_builder_text(workout: Workout) -> str:
    """Convert a Workout back into builder syntax, one step per line.

    Each interval becomes its own '- <duration> <spec>' line. Repeats are
    not reconstructed; identical repeated steps are simply listed in full.
    """
    lines: list[str] = []
    for iv in workout.intervals:
        dur = _format_duration_token(iv.duration_seconds)
        if iv.free_ride:
            spec = "free"
        elif iv.is_ramp:
            spec = (
                f"ramp {_format_pct_token(iv.start_percent_ftp)}-"
                f"{_format_pct_token(iv.end_percent_ftp)}%"
            )
        else:
            spec = f"{_format_pct_token(iv.start_percent_ftp)}%"
        lines.append(f"- {dur} {spec}")
    return "\n".join(lines)

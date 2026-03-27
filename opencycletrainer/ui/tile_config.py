from __future__ import annotations

MAX_CONFIGURABLE_TILES = 8

TILE_OPTIONS: tuple[tuple[str, str], ...] = (
    ("windowed_avg_ftp", "Windowed Avg %FTP"),
    ("interval_avg_power", "Interval Avg Power"),
    ("workout_avg_power", "Workout Avg Power"),
    ("workout_normalized_power", "Workout Normalized Power"),
    ("heart_rate", "Heart Rate"),
    ("workout_avg_hr", "Workout Avg HR"),
    ("interval_avg_hr", "Interval Avg HR"),
    ("kj_work_completed", "kJ Work Completed"),
    ("kj_work_completed_interval", "kJ Work (Interval)"),
    ("cadence_rpm", "Cadence"),
)

TILE_LABEL_BY_KEY = {key: label for key, label in TILE_OPTIONS}


def normalize_tile_selections(tile_selections: list[str]) -> list[str]:
    selected: list[str] = []
    for key in tile_selections:
        if key not in TILE_LABEL_BY_KEY:
            continue
        if key in selected:
            continue
        selected.append(key)
        if len(selected) == MAX_CONFIGURABLE_TILES:
            break
    return selected

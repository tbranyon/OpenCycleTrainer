from __future__ import annotations

from pathlib import Path

import pytest

from opencycletrainer.integrations.strava.chart_export import (
    DEFAULT_HEIGHT_PX,
    DEFAULT_WIDTH_PX,
    generate_workout_chart_image,
)


def test_default_dimensions_are_portrait() -> None:
    """Default dimensions should be portrait (height > width) for Strava feed."""
    assert DEFAULT_HEIGHT_PX > DEFAULT_WIDTH_PX


def test_default_width_is_1080() -> None:
    assert DEFAULT_WIDTH_PX == 1080


def test_default_height_is_1350() -> None:
    assert DEFAULT_HEIGHT_PX == 1350


def test_generate_image_creates_file(tmp_path: Path) -> None:
    output = tmp_path / "chart.jpg"
    result = generate_workout_chart_image(
        [(0.0, 200), (60.0, 250), (120.0, 180)],
        output,
    )
    assert result == output
    assert output.exists()
    assert output.stat().st_size > 0


def test_generate_image_with_empty_series(tmp_path: Path) -> None:
    """An empty power series should still produce a valid image file."""
    output = tmp_path / "chart_empty.jpg"
    result = generate_workout_chart_image([], output)
    assert result == output
    assert output.exists()
    assert output.stat().st_size > 0


def test_generate_image_returns_output_path(tmp_path: Path) -> None:
    output = tmp_path / "chart.jpg"
    result = generate_workout_chart_image([(0.0, 150)], output)
    assert result == output


def test_generate_image_with_long_series(tmp_path: Path) -> None:
    output = tmp_path / "chart_long.jpg"
    series = [(float(i), 200 + (i % 50)) for i in range(3600)]
    result = generate_workout_chart_image(series, output)
    assert result == output
    assert output.stat().st_size > 0

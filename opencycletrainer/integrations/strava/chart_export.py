from __future__ import annotations

import logging
import tempfile
from pathlib import Path

_logger = logging.getLogger(__name__)

DEFAULT_WIDTH_PX = 1080
DEFAULT_HEIGHT_PX = 1350


def generate_workout_chart_image(
    power_series: list[tuple[float, int]],
    output_path: Path,
    *,
    width_px: int = DEFAULT_WIDTH_PX,
    height_px: int = DEFAULT_HEIGHT_PX,
    dpi: int = 96,
) -> Path:
    """Render a power-vs-time chart to a JPEG file at feed-friendly dimensions.

    Returns output_path on success.
    """
    import matplotlib  # noqa: PLC0415

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt  # noqa: PLC0415

    fig, ax = plt.subplots(figsize=(width_px / dpi, height_px / dpi), dpi=dpi)

    if power_series:
        times = [t for t, _ in power_series]
        watts = [w for _, w in power_series]
        ax.fill_between(times, watts, alpha=0.35, color="#4FC3F7")
        ax.plot(times, watts, color="#0288D1", linewidth=1.5)

    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Power (W)")
    ax.set_title("Workout Power")
    ax.grid(True, alpha=0.3)

    fig.tight_layout()
    fig.savefig(output_path, format="jpeg", dpi=dpi)
    plt.close(fig)

    return output_path

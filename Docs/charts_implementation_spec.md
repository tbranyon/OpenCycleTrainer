# Live Workout & Interval Charts — Implementation Spec

## Overview

Two live charts on the workout screen:
1. **Workout Chart** — full workout view, entire duration visible at all times
2. **Interval Chart** — zoomed view of the current interval ± 30 s context padding from adjacent intervals

Both update on a 1-second timer tick.

---

## Visual Design

### Series / Layers

| Series | Chart | Color | Style |
|---|---|---|---|
| Target power | Both | Blue (`#3b82f6`) | Filled area under the step/ramp line; fill is light blue (`rgba(59,130,246,0.25)`) |
| Actual power (bike PM if connected, else trainer power) | Both | Green (`#22c55e`) | 1–2 px line, no fill |
| Heart rate (if HR source connected) | Both | Red (`#ef4444`) | 1–2 px line, no fill; plotted on the same Y axis as watts without unit scaling |
| Current-position indicator | Both | Light grey (`rgba(200,200,200,0.7)`) | Slim vertical bar / `InfiniteLine` at elapsed position |
| FTP annotation | Both | Muted grey (`rgba(150,150,150,0.5)`) | Thin dashed horizontal line; "FTP" text label pinned to right edge, small font |

### Y Axis (Watts)

- Single left-side axis, unit = Watts.
- HR bpm values are plotted directly on this axis without any secondary axis or scaling. The numeric overlap between HR (e.g. 140 bpm) and power (e.g. 140 W) is accepted by design.
- **Grid lines**: horizontal dashed grid lines every 50 W (i.e. at 50, 100, 150, 200, … W), labelled on the Y axis tick marks. Grid lines should be subtle — thin, low-opacity.
- Y range: auto-scaled to `max(target_peak, actual_peak, hr_peak, ftp) * 1.10`, recomputed at chart load and optionally updated live as actuals arrive. FTP line is always visible within range.

### X Axis (Time)

- Unit: seconds internally; display labels as `MM:SS`.
- **Tick density**: exactly **8 evenly-spaced ticks** spanning the full visible x range at all times, including one tick at the left edge and one at the right edge (i.e. ticks at 0, span/7, 2·span/7, …, span). The tick interval is therefore `span / 7` seconds, rounded to a clean value if desired (see note below).
- Both inner and outer tick marks are shown.
- Labels at every tick mark.
- As the interval chart's x range shifts when intervals change, the tick interval is recomputed for the new span so that 8 ticks are always shown across the new window.

> **Implementation note — tick spacing**: pyqtgraph's `AxisItem` supports a custom `tickSpacing` override. Compute `major_spacing = visible_span / 7` and pass `[(major_spacing, 0)]` to `axis.setTickSpacing(...)` after each range change. If you want cleaner numbers (e.g. round to nearest 10 s), use `round(major_spacing / 10) * 10` with a minimum of 1 s — this is a minor polish decision, not a hard requirement. Decision: we should round to the nearest 5s.

### Layout / Sizing

- Charts are stacked vertically below the metric tiles.
- Interval chart on top, workout chart below.
- Suggested height ratio: interval ≈ 60 %, workout ≈ 40 % of total chart area — tweak to taste.
- Charts expand to fill available horizontal space and remaining vertical space (free-flow, no fixed minimum height).

---

## Chart Behaviour

### Workout Chart

- Target power profile rendered **at workout load time**, covering the full duration, as a filled blue step/ramp area. Ramp intervals draw a sloped line (trapezoidal fill) connecting start-target to end-target.
- Actual power trace grows from left as data accumulates (one point per second).
- HR trace grows the same way.
- Current-position indicator moves right in real time.
- X axis range is fixed to `[0, total_duration_seconds]` — never scrolls.
- On workout end (stop or finish): charts **freeze** in place showing the completed trace. They remain visible below the "workout saved" alert.

### Interval Chart

- X axis range = `[interval_start - 30s, interval_end + 30s]`, clamped to `[0, total_duration_seconds]`.
- When interval changes, the x range shifts to the new interval window and tick spacing is recomputed.
- The 30 s padding on each side shows the tail/head of adjacent intervals in the target trace, giving visual context.
- Actual power and HR traces are shown for the visible window only (slice from accumulated history).
- Current-position indicator moves within the interval window.
- **Before the first interval** (`current_interval_index is None`, e.g. during `RAMP_IN`): show the first interval's window (index 0).

### Pausing

- Traces freeze when the workout is paused (no new data points added).
- Current-position indicator continues to reflect the paused elapsed time (static).

---

## Data Requirements

### What already exists (no new collection needed)

- `_power_history: deque[tuple[float, int]]` — (monotonic_timestamp, watts). Available in `WorkoutSessionController`.
- `_last_hr_bpm: int | None`
- `_last_bike_power_watts: int | None`, `_last_power_watts: int | None`
- `Workout.intervals` — full target power profile computable at load time.
- `WorkoutEngineSnapshot.elapsed_seconds`, `current_interval_index`, `current_interval_elapsed_seconds`.

### New data collection needed

| What | Where to add |
|---|---|
| HR timeseries: `list[tuple[float, int]]` of `(elapsed_seconds, bpm)` | Append in `receive_hr_bpm` when `_recorder_active` |
| Session start monotonic timestamp: `_chart_start_monotonic: float` | Set in `_start_workout` |

**Power series elapsed-time mapping**: at each 1 s chart tick, convert `_power_history` entries to elapsed time via `elapsed = mono_t - _chart_start_monotonic`. No separate structure needed — derive on the fly at chart-update time.

**Primary power source**: use `_last_bike_power_watts` when not `None`, otherwise `_last_power_watts` (trainer). This is consistent with "bike PM is the primary PM". Revisit when TODO #8 (primary power source persistence) is implemented.

---

## Charting Library

**Recommended: `pyqtgraph`**

- Native Qt widgets, no separate canvas/figure lifecycle.
- High-performance for real-time 1 Hz update with ~3600 point series (60 min workout).
- `PlotWidget`, `PlotDataItem`, `InfiniteLine`, `TextItem`, `AxisItem` cover all required primitives.
- Add `pyqtgraph>=0.13` to project dependencies.

Alternative: `matplotlib` with `FigureCanvasQTAgg`. More familiar but slower and heavier for embedded real-time use. Not recommended here.

---

## Implementation Tasks

### ~~Task 1 — Add pyqtgraph dependency~~ Done
- Add `pyqtgraph>=0.13` to `pyproject.toml` / `requirements.txt`.
- Verify import in a quick smoke test or existing test harness.

### Task 2 — Build `WorkoutChartWidget` (`opencycletrainer/ui/workout_chart.py`)
A `QWidget` wrapping two `pyqtgraph.PlotWidget` instances:

```
WorkoutChartWidget  (QWidget, QVBoxLayout)
├── IntervalPlotWidget   (pyqtgraph.PlotWidget)
└── WorkoutPlotWidget    (pyqtgraph.PlotWidget)
```

**Constructor**: no required args — widget starts in an empty/idle state.

**Public API**:

```python
def load_workout(self, workout: Workout, ftp_watts: int) -> None:
    """Rebuild static target series, reset live series, configure axes."""

def update_charts(
    self,
    elapsed_seconds: float,
    current_interval_index: int | None,
    power_series: list[tuple[float, int]],
    hr_series: list[tuple[float, int]],
) -> None:
    """Called once per second from the controller while workout is running."""

def clear(self) -> None:
    """Reset to idle state (called on new workout load, not on stop)."""
```

**Internal helpers**:

- `_build_target_series(workout: Workout) -> tuple[np.ndarray, np.ndarray]`
  Returns `(t, w)` arrays covering full workout. For each interval: if not a ramp, emit two points (start and end of interval at constant watts); if a ramp, emit two points (start and end at their respective target watts). Prepend/append boundary points as needed so the fill goes to zero at both ends.

- `_configure_y_axis(plot: PlotWidget, y_max: float) -> None`
  Sets range, enables 50 W grid lines, sets tick spacing to 50.

- `_configure_x_axis(plot: PlotWidget, x_min: float, x_max: float) -> None`
  Sets range and computes tick spacing = `(x_max - x_min) / 7`, updates `axis.setTickSpacing([(spacing, 0)])`. Formats labels as `MM:SS` via a custom `AxisItem` subclass or `tickStrings` override.

- `_update_position_indicator(elapsed_seconds: float) -> None`
  Moves `InfiniteLine` on both plots to `x = elapsed_seconds`.

- `_update_interval_range(interval_index: int | None, workout: Workout) -> None`
  Computes `[x_min, x_max]` for the interval plot and calls `_configure_x_axis`.

- `_reposition_ftp_label(plot: PlotWidget) -> None`
  Called on `sigXRangeChanged` / `sigYRangeChanged` to keep the "FTP" `TextItem` pinned to the right edge of the view in data coordinates.

**Styling details**:
- Background: match the application's existing dark/light theme (do not hardcode a background color — use `setBackground('default')` or `'w'` to match).
- Grid: `plot.showGrid(x=False, y=True, alpha=0.3)` with `y_axis.setTickSpacing([(50, 0)])` to get lines only at 50 W intervals.
- FTP line: `InfiniteLine(angle=0, movable=False, pos=ftp_watts, pen=pg.mkPen(color=(150,150,150), width=1, style=Qt.DashLine))`.
- FTP label: `TextItem("FTP", color=(150,150,150), anchor=(1, 1))` — small font, right-aligned.

### Task 3 — Integrate into `WorkoutScreen`
- Replace the two TODO `QLabel` placeholders in `_build_chart_scaffolding` with an instance of `WorkoutChartWidget`.
- Remove the now-redundant `QGroupBox` wrappers or keep them as titled containers — your call.
- Add forwarding methods on `WorkoutScreen`:
  - `load_workout_chart(workout: Workout, ftp_watts: int)`
  - `update_charts(elapsed_seconds, interval_index, power_series, hr_series)`
  - `clear_charts()` — not called on stop/finish (freeze in place); only called when a new workout is loaded.

### Task 4 — Wire controller → charts in `WorkoutSessionController`
- Add `_chart_start_monotonic: float | None = None` and `_hr_history: list[tuple[float, int]] = []`.
- Add a `_chart_timer: QTimer` with 1000 ms interval; connect to `_on_chart_tick`.
- In `_start_workout`:
  - Set `_chart_start_monotonic = self._monotonic_clock()`.
  - Clear `_hr_history`.
  - Call `self._screen.load_workout_chart(self._workout, self._settings.ftp)`.
  - Start `_chart_timer`.
- In `receive_hr_bpm`: when `_recorder_active` and bpm is not None, append `(elapsed_from_start, bpm)` to `_hr_history`.
- In `_on_chart_tick`:
  - Compute `elapsed = now - _chart_start_monotonic`.
  - Build `power_series` by translating `_power_history` monotonic timestamps → elapsed seconds.
  - Determine `current_interval_index` from `_last_snapshot`.
  - Call `self._screen.update_charts(elapsed, current_interval_index, power_series, _hr_history)`.
- In `_stop_workout` and `_skip_interval` (when finished): stop `_chart_timer` but do **not** clear charts (freeze).
- In `_load_workout_from_file`: call `self._screen.clear_charts()` before loading new workout.
- In `shutdown`: stop `_chart_timer`.

### Task 5 — Custom `MM:SS` time axis
Create a small `TimeAxisItem(pyqtgraph.AxisItem)` subclass that overrides `tickStrings`:

```python
class TimeAxisItem(pg.AxisItem):
    def tickStrings(self, values, scale, spacing):
        return [f"{int(v)//60:02}:{int(v)%60:02}" for v in values]
```

Pass an instance to each `PlotWidget` as `axisItems={'bottom': TimeAxisItem('bottom')}`.

### Task 6 — Tests
- Unit test `WorkoutChartWidget` in isolation (headless: set `QT_QPA_PLATFORM=offscreen`):
  - Load a workout, verify target series has the correct length and watt values at known interval boundaries.
  - Call `update_charts` 3 times, assert power/HR series lengths increase.
  - Assert position indicator `.value` equals the passed `elapsed_seconds`.
  - Assert tick spacing on interval plot is recomputed when interval index changes.
- Controller-level tests:
  - Verify `_chart_timer` starts on `_start_workout` and stops on `_stop_workout`.
  - Verify `_hr_history` accumulates correctly via `receive_hr_bpm`.
  - Verify `load_workout_chart` is called with correct `ftp_watts` from settings.

---

## Decisions Log

| # | Question | Decision |
|---|---|---|
| 1 | HR on same Y axis as watts? | Yes — accept visual overlap, no secondary axis |
| 2 | Primary power source for green line? | Bike PM when connected, fallback to trainer power |
| 3 | Ramp interval fill shape? | Trapezoidal (sloped line, accurate fill) |
| 4 | Charts on workout end? | Freeze in place; remain visible below "saved" alert |
| 5 | Interval chart before first interval? | Show first interval window (index 0) |
| 6 | Chart height? | Free-flow to fill available vertical space |
| 7 | Y axis grid lines? | Horizontal dashed lines every 50 W with axis labels |
| 8 | X axis ticks? | 8 ticks across full visible span (including both endpoints); inner + outer tick marks; labels as MM:SS; tick interval recomputed on x range change |

---

## Out of Scope (this task)

- Historical/post-workout chart on a summary screen (separate future task).
- Lap/segment annotations on the workout chart.
- Exporting chart as image.
- Zoom/pan interactivity (charts are view-only during workout).
- Secondary Y axis for HR bpm.

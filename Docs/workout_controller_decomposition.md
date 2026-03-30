# WorkoutSessionController Decomposition Plan

## Context

`WorkoutSessionController` (`opencycletrainer/ui/workout_controller.py`, ~1,189 lines) has grown to mix 11 distinct concerns: power history, cadence history, per-interval stats, mode state, OpenTrueUp state, pause state, chart history, tile computation, FTMS bridge management, recorder integration, and trainer connection tracking.

This makes it hard to unit-test individual behaviors in isolation and difficult to reason about interactions between concerns. The goal is to decompose it into focused sub-objects while keeping the public API (`set_trainer_control_target`, `apply_settings`, `load_workout`, `process_tick`, `receive_*`, `shutdown`, `last_snapshot`) completely stable from `MainWindow`'s perspective.

---

## Constraints

- **Public API is frozen.** `MainWindow` must not need to change.
- **TDD.** Write sub-object unit tests before implementing each sub-object.
- **Incremental.** All 48 existing `test_workout_controller.py` tests must stay green after each step.
- **Compatibility bridges.** Tests that access `controller._something` get a `@property` delegating to the sub-object; these are removed in a later cleanup pass.
- **One step per PR/commit.** Verify full test suite passes before proceeding to the next step.

---

## Extraction Order

Order is determined by independence (fewest inbound dependencies from other new sub-objects), then testability gain.

| Step | Sub-object | File | Direction |
|------|-----------|------|-----------|
| 1 | `PowerHistory` | `core/power_history.py` | Pure data, no Qt |
| 2 | `CadenceHistory` | `core/cadence_history.py` | Pure data, no Qt |
| 3 | `IntervalStats` | `core/interval_stats.py` | Pure data, no Qt |
| 4 | `ModeState` | `ui/mode_state.py` | Pure logic, no Qt |
| 5 | `PauseState` | `ui/pause_state.py` | Owns `PauseDialog` |
| 6 | `ChartHistory` | `ui/chart_history.py` | Owns `QTimer`, reads PowerHistory |
| 7 | `RecorderIntegration` | `ui/recorder_integration.py` | Fan-out, high coordination |
| 8 | `OpenTrueUpState` | `ui/opentrueup_state.py` | Thin wrapper |
| 9 | `FTMSBridgeManager` | `ui/ftms_bridge_manager.py` | Thread-pool, high risk |
| 10 | `TrainerConnection` | `ui/trainer_connection.py` | Thin delegator |
| 11 | `TileComputation` | `ui/tile_computation.py` (compute in `core/`) | Highest independent test value |

---

## Sub-Object Specifications

### 1. `PowerHistory` — `core/power_history.py`

**Owns:**
- `_power_history: deque[tuple[float, int]]` — rolling samples
- `_last_actual_power_tick: float | None`
- `_workout_power_sum`, `_workout_power_count`
- `_workout_actual_kj: float`

**Interface:**
```python
PowerHistory()

record(watts: int, now: float, recording_active: bool) -> None
windowed_avg(now: float, window_seconds: int) -> int | None
compute_normalized_power() -> int | None
workout_avg_watts() -> int | None
workout_actual_kj() -> float
reset() -> None
as_series() -> list[tuple[float, int]]
```

**Controller delegation:**
- `receive_power_watts()` → `self._power_history.record(watts, now, recording_active)`
- `_windowed_avg_power()` → `self._power_history.windowed_avg(now, window)`
- `_compute_normalized_power()` → `self._power_history.compute_normalized_power()`
- `_update_total_kj()` removed; kJ now accumulated inside `record()`
- Workout start/free-ride start → `self._power_history.reset()`

**New test file:** `tests/test_power_history.py`

---

### 2. `CadenceHistory` — `core/cadence_history.py`

**Owns:**
- `_cadence_history: deque[tuple[float, float]]`
- `_cadence_source_last_times: dict[CadenceSource, float]`
- `_last_cadence_rpm: float | None`

**Interface:**
```python
CadenceHistory(staleness_seconds: float = 3.0)

record(rpm: float | None, source: CadenceSource, now: float) -> None
last_rpm() -> float | None
windowed_avg(now: float) -> int | None
active_source(now: float) -> CadenceSource | None
```

**Controller delegation:**
- `receive_cadence_rpm()` → `self._cadence_history.record(rpm, source, now)`
- `_active_cadence_source()` → `self._cadence_history.active_source(now)`
- `_windowed_avg_cadence()` → `self._cadence_history.windowed_avg(now)`
- `controller._last_cadence_rpm` → `@property` returning `self._cadence_history.last_rpm()`
- `controller._cadence_history` → `@property` returning deque (for test compat during migration)

**New test file:** `tests/test_cadence_history.py`

---

### 3. `IntervalStats` — `core/interval_stats.py`

**Owns:**
- `_interval_power_sum`, `_interval_power_count`
- `_interval_actual_kj: float`, `_last_actual_power_tick: float | None` (interval-scoped)
- `_interval_hr_sum`, `_interval_hr_count`
- `_workout_hr_sum`, `_workout_hr_count`

Note: Workout-level power stats belong to `PowerHistory`. Interval-level actual kJ requires its own `_last_actual_power_tick` — intentional duplication to avoid a dependency between sub-objects.

**Interface:**
```python
IntervalStats()

record_power(watts: int, now: float, recording_active: bool) -> None
record_hr(bpm: int) -> None
reset_interval() -> None
reset_workout() -> None
interval_avg_watts() -> int | None
interval_actual_kj() -> float
interval_avg_hr() -> int | None
workout_avg_hr() -> int | None
```

**Controller delegation:**
- `receive_power_watts()` calls both `self._power_history.record(...)` and `self._interval_stats.record_power(...)`
- `receive_hr_bpm()` → `self._interval_stats.record_hr(bpm)`
- `_reset_interval_accumulators()` → `self._interval_stats.reset_interval()`
- Workout start → `self._interval_stats.reset_workout()`

**New test file:** `tests/test_interval_stats.py`

---

### 4. `ModeState` — `ui/mode_state.py`

**Owns:**
- `_selected_mode: str`
- `_manual_resistance_offset_percent: float`
- `_manual_erg_jog_watts: float`
- `_is_free_ride: bool`
- `_free_ride_erg_target_watts: int | None`
- `_trainer_resistance_step_count: int | None`

**Interface:**
```python
ModeState(initial_selected_mode: str, initial_resistance_offset_percent: float = DEFAULT_MANUAL_RESISTANCE_OFFSET_PERCENT)

active_control_mode(snapshot: WorkoutEngineSnapshot, workout: Workout | None) -> str
resolve_target_watts(snapshot: WorkoutEngineSnapshot, workout: Workout | None) -> int | None
workout_target_watts(snapshot: WorkoutEngineSnapshot, workout: Workout | None) -> int | None
resistance_display() -> tuple[int, bool]
select_mode(mode: str) -> None
jog(delta_percent: int, ftp: float) -> None
reset_jog() -> None
set_free_ride(enabled: bool, erg_target: int | None) -> None
set_erg_target(watts: int) -> None
set_trainer_resistance_step_count(n: int | None) -> None
# Properties: selected_mode, is_free_ride, free_ride_erg_target
```

**Controller delegation:**
- `_active_control_mode()` → `self._mode_state.active_control_mode(snapshot, self._workout)`
- `_resolve_target_watts()` → `self._mode_state.resolve_target_watts(snapshot, self._workout)`
- `_jog_target()` → `self._mode_state.jog(delta_percent, ftp)`
- `_mode_selected()` → `self._mode_state.select_mode(mode)`
- `controller._free_ride_erg_target_watts` → `@property` delegating to `_mode_state`

**New test file:** `tests/test_mode_state.py`

---

### 5. `PauseState` — `ui/pause_state.py`

**Owns:**
- `_pause_dialog: PauseDialog | None`
- `_pause_start_monotonic: float | None`
- `_total_paused_duration: float`

**Interface:**
```python
PauseState(screen: WorkoutScreen, resume_callback: Callable[[], None])

pause(now: float) -> None
resume() -> None
on_ramp_in_to_running(now: float) -> None
total_paused_plus_current(now: float) -> float
close_dialog() -> None
reset() -> None
# Properties: pause_dialog, pause_start_monotonic, total_paused_duration
```

**Controller delegation:**
- `_pause_workout()` → `self._pause_state.pause(now)`
- `_resume_workout()` → `self._pause_state.resume()`
- Transition detection in `_handle_snapshot()` → `self._pause_state.on_ramp_in_to_running(now)`
- `controller._pause_dialog` → `@property` delegating to `_pause_state`

**New test file:** `tests/test_pause_state.py`

---

### 6. `ChartHistory` — `ui/chart_history.py`

**Owns:**
- `_chart_timer: QTimer`
- `_chart_start_monotonic: float | None`
- `_hr_history: list[tuple[float, int]]`
- `_skip_events: list[tuple[float, float, float]]`

**Dependencies (constructor args):** `screen`, `monotonic_clock`, `power_history: PowerHistory`, `pause_state: PauseState`

**Interface:**
```python
ChartHistory(screen, monotonic_clock, power_history, pause_state)

start(now: float) -> None
stop() -> None
reset() -> None
record_hr(bpm: int, now: float) -> None
record_skip(now: float, elapsed_before: float, elapsed_after: float) -> None
on_tick(snapshot, workout, is_free_ride) -> None
# Properties: chart_start_monotonic, hr_history, skip_events, chart_timer
```

**Controller delegation:**
- `_start_workout()` / `_start_free_ride()` → `self._chart_history.start(now)`
- `_stop_workout()` / shutdown → `self._chart_history.stop()`
- `receive_hr_bpm()` when recording → `self._chart_history.record_hr(bpm, now)`
- `_skip_interval()` → `self._chart_history.record_skip(...)`
- `controller._chart_timer` → `@property` delegating to `_chart_history.chart_timer`
- `controller._chart_start_monotonic` → `@property`
- `controller._hr_history` → `@property`

**New test file:** `tests/test_chart_history.py`

---

### 7. `RecorderIntegration` — `ui/recorder_integration.py`

**Owns:**
- `_recorder: WorkoutRecorder`
- `_recorder_active: bool`, `_recorder_started: bool`
- `_total_kj: float` (target-based kJ)
- `_last_energy_tick_monotonic: float | None`
- `_upload_executor: ThreadPoolExecutor | None`

**Interface:**
```python
RecorderIntegration(recorder, screen, settings, settings_path, utc_now, strava_upload_fn, alert_signal, mode_state)

start(workout: Workout, utc_now: datetime) -> None
finalize(workout: Workout) -> None
sync(snapshot, now_monotonic: float, sensor_snapshot: SensorSnapshot) -> None
update_total_kj(snapshot, now_monotonic: float) -> None
configure_data_dir(settings: AppSettings) -> None
shutdown() -> None
# Properties: recorder_active, total_kj
```

`SensorSnapshot` is a lightweight dataclass carrying `last_power_watts`, `last_bike_power_watts`, `last_hr_bpm`, `last_cadence_rpm`, `last_speed_mps`.

**Controller delegation:**
- `_start_recorder()` → `self._recorder_integration.start(...)`
- `_finalize_recorder()` → `self._recorder_integration.finalize(...)`
- `_sync_recorder()` → `self._recorder_integration.sync(snapshot, now_monotonic, sensor_snapshot)`
- `_update_total_kj()` → `self._recorder_integration.update_total_kj(snapshot, now_monotonic)`

**New test file:** `tests/test_recorder_integration.py`

---

### 8. `OpenTrueUpState` — `ui/opentrueup_state.py`

**Owns:**
- `_opentrueup: OpenTrueUpController | None`

**Interface:**
```python
OpenTrueUpState(opentrueup: OpenTrueUpController | None, offset_signal)

feed(timestamp: float, trainer_watts: int | None, bike_watts: int | None) -> None
handle_bridge_status(status) -> None
enable(settings: AppSettings) -> None
disable() -> None
# Properties: controller, enabled
```

**Controller delegation:**
- `_feed_opentrueup()` → `self._opentrueup_state.feed(...)`
- `_handle_bridge_opentrueup_status()` → `self._opentrueup_state.handle_bridge_status(...)`
- `controller._opentrueup` → `@property` returning `self._opentrueup_state.controller`

No new test file needed beyond updating `test_workout_controller.py` internal-access tests.

---

### 9. `FTMSBridgeManager` — `ui/ftms_bridge_manager.py`

**Owns:**
- `_ftms_bridge: WorkoutEngineFTMSBridge | None`
- `_ftms_bridge_executor: ThreadPoolExecutor | None`

**Interface:**
```python
FTMSBridgeManager(transport_factory, screen, alert_signal, opentrueup_state, mode_state, settings, engine)

configure(backend, device_id: str | None) -> None
teardown() -> None
submit_snapshot(snapshot, workout) -> None
submit_power_sample(timestamp: float, trainer_watts: int | None, bike_watts: int | None) -> None
submit_action(action: Callable) -> None
# Properties: active
```

**Risk:** Thread-pool action dispatch. The existing `current_bridge = self._ftms_bridge` guard before executor submission must be preserved verbatim.

**Controller delegation:**
- `_reconfigure_ftms_bridge()` → `self._ftms_bridge_manager.configure(...)`
- `_teardown_ftms_bridge()` → `self._ftms_bridge_manager.teardown()`
- `_submit_ftms_bridge_action()` → `self._ftms_bridge_manager.submit_action(...)`
- `_submit_snapshot_to_ftms_bridge()` → `self._ftms_bridge_manager.submit_snapshot(...)`
- `_dispatch_power_sample()` → `self._ftms_bridge_manager.submit_power_sample(...)`

---

### 10. `TrainerConnection` — `ui/trainer_connection.py`

**Owns:**
- `_trainer_backend: object | None`
- `_trainer_device_id: str | None`
- `_last_known_trainer_id: str | None`

**Interface:**
```python
TrainerConnection(screen, ftms_bridge_manager, is_workout_active: Callable[[], bool])

set_target(backend, trainer_device_id: str | None) -> None
# Properties: backend, device_id, last_known_id
```

**Controller delegation:**
- `set_trainer_control_target()` → `self._trainer_connection.set_target(backend, trainer_device_id)`
- `_notify_trainer_connection_change()` moves inside `TrainerConnection.set_target()`

---

### 11. `TileComputation` — `ui/tile_computation.py`

**Owns:** No mutable state. Holds read-only references to sub-objects.

**Interface:**
```python
TileComputation(power_history, cadence_history, interval_stats, monotonic_clock)

compute(key: str, snapshot, settings: AppSettings) -> str
update_screen(screen, snapshot, settings) -> None
```

**Controller delegation:**
- `_update_tiles()` → `self._tile_computation.update_screen(self._screen, snapshot, self._settings)`
- `_compute_tile_value()` → `self._tile_computation.compute(key, snapshot, self._settings)`

**New test file:** `tests/test_tile_computation.py` — highest independent test value of all steps.

---

## File Layout After Full Decomposition

```
opencycletrainer/
  core/
    power_history.py          # NEW (Step 1)
    cadence_history.py        # NEW (Step 2)
    interval_stats.py         # NEW (Step 3)
  ui/
    workout_controller.py     # SLIMMED — public API + delegation glue
    mode_state.py             # NEW (Step 4)
    pause_state.py            # NEW (Step 5)
    chart_history.py          # NEW (Step 6)
    recorder_integration.py   # NEW (Step 7)
    opentrueup_state.py       # NEW (Step 8)
    ftms_bridge_manager.py    # NEW (Step 9)
    trainer_connection.py     # NEW (Step 10)
    tile_computation.py       # NEW (Step 11)
  tests/
    test_power_history.py         # NEW
    test_cadence_history.py       # NEW
    test_interval_stats.py        # NEW
    test_mode_state.py            # NEW
    test_tile_computation.py      # NEW
    test_recorder_integration.py  # NEW
    test_workout_controller.py    # UPDATED (remove migrated internal-access tests over time)
```

---

## Test Migration Strategy

Tests that access `controller._something` fall into two phases:

**Phase A (during extraction):** Add a `@property` on `WorkoutSessionController` that delegates to the new sub-object. All 48 existing tests remain green with no edits.

Example:
```python
@property
def _pause_dialog(self):
    return self._pause_state.pause_dialog
```

**Phase B (cleanup, separate PR):** Once sub-object unit tests cover the behavior, remove the `@property` bridges and update or delete the corresponding integration tests.

Internal attribute targets and their compatibility properties:

| Attribute | Migrates to |
|-----------|-------------|
| `_pause_dialog` | `_pause_state.pause_dialog` |
| `_chart_timer` | `_chart_history.chart_timer` |
| `_chart_start_monotonic` | `_chart_history.chart_start_monotonic` |
| `_hr_history` | `_chart_history.hr_history` |
| `_last_cadence_rpm` | `_cadence_history.last_rpm()` |
| `_cadence_history` (deque) | `_cadence_history` (the object) |
| `_opentrueup` | `_opentrueup_state.controller` |
| `_free_ride_erg_target_watts` | `_mode_state.free_ride_erg_target` |

---

## Risks and Mitigations

| Step | Risk | Mitigation |
|------|------|-----------|
| 1 — PowerHistory | Low | 10+ isolated unit tests before touching controller |
| 2 — CadenceHistory | Low | Same; direct analog |
| 3 — IntervalStats | Medium — reset timing tied to snapshot interval boundary | Test reset protocol explicitly in isolation |
| 4 — ModeState | Medium — called from multiple paths (FTMS, recorder, tiles) | Pass same snapshot instance; no shared mutable reference |
| 5 — PauseState | Medium — RAMP_IN→RUNNING transition is fragile | Port chart cursor tests as unit tests before extraction |
| 6 — ChartHistory | Medium — pause offset math and skip event timing | Port chart timer tests to sub-object level first |
| 7 — RecorderIntegration | High — Strava Future callbacks, sensor fan-out | Keep integration tests in `test_workout_controller.py` throughout; add isolated unit tests in parallel |
| 9 — FTMSBridgeManager | High — thread-pool, teardown race | Preserve `current_bridge` guard verbatim; no logic changes during extraction |

---

## Verification

After each step, run the full test suite:
```
python -m pytest
```

All 48 tests in `test_workout_controller.py` plus new sub-object tests must pass before proceeding.

After all steps, `workout_controller.py` should be reduced from ~1,189 lines to a thin orchestration layer of ~300–400 lines containing only: constructor (sub-object wiring), public API methods, `_handle_snapshot()` (main coordination), and `_wire_screen_actions()`.

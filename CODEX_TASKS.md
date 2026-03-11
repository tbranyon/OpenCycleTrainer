from pathlib import Path

spec_path = Path("/mnt/data/OpenCycleTrainer_Codex_Tasks.md")

content = """# OpenCycleTrainer â€” Codex Task Queue (v1)
This file is meant to live in the repo root and be used as the *single source of truth* for Codex task execution.

Reference spec (source of truth): `AppSpec.md`.
- Keep the implementation aligned with the requirements in the spec.
- Prefer small, testable increments.
- Add/extend tests with each task.

---

## How to use this file with Codex
Recommended workflow:
1. Copy this file into your repository root as `CODEX_TASKS.md`.
2. In Codex, use the **â€œSuggested Codex promptâ€** for the current task.
3. When a task is complete, mark it as **DONE** and move to the next.

Rules for Codex:
- Do not refactor unrelated code.
- Keep BLE and trainer control isolated behind interfaces.
- Ensure the UI never blocks on BLE operations.
- Prefer deterministic unit tests with mock/simulated backends.
- If this document conflicts with the spec, the spec takes precedence.

---

## Task 00 â€” Repository scaffold + quality gates (STATUS: DONE)

### Goal
Create a runnable PySide6 application skeleton with a clean module layout, logging, settings storage, and test runner.

### Deliverables
- Project structure:
  - `opencycletrainer/`
    - `__init__.py`
    - `app.py` (Qt application entry)
    - `ui/` (Qt widgets)
    - `core/` (workout engine, control, recorder)
    - `devices/` (BLE abstractions)
    - `storage/` (paths, settings persistence, offsets)
    - `tests/`
  - `pyproject.toml` (or `requirements.txt` + minimal packaging metadata)
  - `README.md` (dev setup + run commands)
  - `.gitignore`
- Logging to console + file
- Settings storage (local) with placeholder keys: FTP, lead_time, OpenTrueUp enabled, tile selections
- Unit test setup (pytest)

### Acceptance Criteria
- `python -m opencycletrainer` launches a window titled â€œOpenCycleTrainerâ€.
- `pytest` runs and passes (at least one trivial test).
- Settings file is created on first run.

### Suggested Codex prompt
â€œImplement Task 00 from CODEX_TASKS.md. Create the repository scaffold, PySide6 app entry, logging, settings persistence, and pytest setup. Do not implement BLE yet. Provide commands to run the app and tests.â€

---

## Task 01 â€” Storage paths + filename rules (STATUS: DONE)

### Goal
Implement platform-specific storage paths and filename generation per spec.

### Deliverables
- `storage/paths.py`:
  - Windows: `%APPDATA%\\OpenCycleTrainer\\` for config
  - Linux: `~/.config/opencycletrainer/` for config and `~/.local/share/opencycletrainer/` for data
- `storage/filenames.py` for activity filenames:
  - `[WorkoutName]_[YYYYMMDD]_[HHMM].[EXT]` (e.g., `Threshold_20260309_1842.fit`)

### Acceptance Criteria
- Unit tests verifying output paths and filename formatting.
- Directory creation on demand.

### Suggested Codex prompt
â€œImplement Task 01 from CODEX_TASKS.md: storage paths and activity filename generation with unit tests. Keep code cross-platform.â€

---

## Task 02 â€” Workout file import: MRC parser (STATUS: DONE)

### Goal
Parse MRC files with MINUTES/PERCENT into an internal workout model supporting steps and linear ramps.

### Deliverables
- `core/workout_model.py` (internal canonical model)
- `core/mrc_parser.py`
- Test vectors in `tests/data/` with unit tests:
  - step-only MRC
  - ramp MRC

### Notes
- Text cues not supported.
- PERCENT is relative to FTP (stored in settings).

### Acceptance Criteria
- Given an MRC and FTP, the parser produces a sequence of intervals with target %FTP and duration.
- Ramps represented as start% -> end% over duration.
- Unit tests cover parsing and basic validation (bad files rejected with clear error).

### Suggested Codex prompt
â€œImplement Task 02: MRC parser + internal workout model + tests. Follow CODEX_TASKS.md. Do not implement UI yet beyond placeholders.â€

---

## Task 03 â€” Workout engine state machine (STATUS: DONE)

### Goal
Implement a workout runner that advances through intervals over time, supports pause/resume, skip interval, extend interval, and kJ mode placeholder hooks.

### Deliverables
- `core/workout_engine.py`
- Engine API:
  - `load_workout(workout)`
  - `start()`, `pause()`, `resume()`, `stop()`
  - `tick(now)` (driven by a timer)
  - commands: `skip_interval()`, `extend_interval(seconds_or_kj)`
- Tests using simulated time.

### Acceptance Criteria
- Interval progression matches expected schedule.
- Pause stops progression.
- Resume triggers â€œramp-in activeâ€ state for 3 seconds (recording stays paused during ramp-in).
- Skip jumps to next interval end.
- Extend adds 1min/5min (or 10kJ/50kJ in kJ mode; implement time-based now, stub for kJ).

### Suggested Codex prompt
â€œImplement Task 03: workout engine state machine + tests. Use a deterministic simulated clock. Include ramp-in countdown state on resume per spec.â€

---

## Task 04 â€” Devices UI (no BLE yet): paired/unpaired lists (STATUS: TODO)

### Goal
Build the Devices screen UI with mocked data sources and correct UX structure.

### Deliverables
- `ui/devices_screen.py` with:
  - Paired devices section
  - Available devices section (filtered by relevant types)
  - Actions: pair, unpair, connect, disconnect, calibrate (enabled only for strain-gauge PM)
  - Fields: name, type, connection status, battery (if known)
- Mock device backend in `devices/mock_backend.py`

### Acceptance Criteria
- UI shows paired vs available distinctly.
- Calibrate button only appears/enabled for PM type that supports it.
- No BLE code yet; must be driven by mock backend.

### Suggested Codex prompt
â€œImplement Task 04: Devices screen UI using PySide6 with a mock devices backend. Follow CODEX_TASKS.md. No real BLE calls.â€

---

## Task 05 â€” BLE backend skeleton (Bleak): scan/connect/notify (STATUS: DONE)

### Goal
Add a Bleak backend that can scan, connect, and subscribe to notifications for FTMS/CPS/HRS/CSC devices.

### Deliverables
- `devices/ble_backend.py` using Bleak (async)
- `devices/types.py` defining device types and relevant service UUID filters
- `devices/device_manager.py` interface implemented by both mock and Bleak backends
- Minimal integration into Devices screen (toggle between mock and real)

### Acceptance Criteria
- Can scan and list devices (name/address/RSSI).
- Filter to relevant devices only (trainers, power meters, HR, cadence).
- Connect/disconnect without UI blocking.
- Notification subscription plumbing exists (no decoding required yet).

### Suggested Codex prompt
â€œImplement Task 05: Bleak BLE backend skeleton + device manager abstraction. Integrate into Devices UI without blocking the Qt UI. Focus on scan/connect/subscribe plumbing; decoding later.â€

---

## Task 06 â€” Decode notifications: power/cadence/HR/speed (STATUS: DONE)

### Goal
Decode CPS, HRS, CSC, and FTMS Indoor Bike Data notifications into a unified sensor stream.

### Deliverables
- `devices/decoders/` modules for each profile
- `core/sensors.py` unified sample model (timestamped)
- Unit tests using byte payload fixtures

### Acceptance Criteria
- Decode produces correct watts/cadence/bpm/speed when present.
- Missing fields handled gracefully.
- Samples are timestamped on receipt.

### Suggested Codex prompt
â€œImplement Task 06: BLE characteristic decoders for CPS/HRS/CSC/FTMS Indoor Bike Data with fixtures and unit tests. Output unified sensor samples.â€

---

## Task 07 - Workout screen UI: metrics + charts (STATUS: DONE)

### Goal
Implement Workout screen with mandatory fields, configurable tiles (up to 8), and basic plotting scaffolding.

### Deliverables
- `ui/workout_screen.py`
- Tile selection settings (persisted; moved to Settings tab in Task 09.5)
- Chart scaffolding (1s power, target, HR) for interval and full workout
  - If a full plotting solution is too heavy initially, stub with placeholder widgets and a clear TODO.

### Acceptance Criteria
- Mandatory fields always visible.
- Up to 8 tiles selectable and persist.
- Controls: Start/Pause/Resume/End.
- Visible mode state (ERG/Resistance/Hybrid).

### Suggested Codex prompt
Implement Task 07: Workout screen UI with mandatory fields, configurable tiles (persisted), and chart scaffolding. Keep code modular and testable.

---

## Task 08 - Recorder: 1 Hz logging + JSON summary (STATUS: DONE)

### Goal
Implement recorder that samples current state at 1 Hz and stores a JSON summary alongside activity files.

### Deliverables
- `core/recorder.py`
- JSON summary schema (minimal):
  - workout name
  - start time UTC
  - duration
  - avg power (placeholder ok if computed later)
- Tests using simulated samples

### Acceptance Criteria
- Recording never blocks control loop.
- JSON summary created with correct filename matching FIT filename stem.

### Suggested Codex prompt
Implement Task 08: 1 Hz recorder + JSON summary + tests. Use non-blocking buffered writes.

---

## Task 09 - FIT export via fit-tool (STATUS: DONE)

### Goal
Write recorded samples to a FIT file via fit-tool.

### Deliverables
- `core/fit_exporter.py`
- Integration with recorder â€œend workoutâ€ path
- Tests that validate:
  - FIT file created
  - contains basic records (timestamp, power, HR, cadence when present)

### Acceptance Criteria
- FIT output filename follows spec.
- FIT timestamps are UTC.
- FIT export works offline with no API.

### Suggested Codex prompt
â€œImplement Task 09: FIT exporter using fit-tool. Integrate with recorder end-of-workout. Add unit/integration tests to confirm FIT creation and basic record content.â€

---

## Task 09.5 - Settings screen UI + move tile selection (STATUS: DONE)

### Goal
Implement the Settings screen and move workout tile selection controls from the Workout screen into Settings.

### Deliverables
- `ui/settings_screen.py`
- Settings controls for:
  - FTP
  - lead time
  - OpenTrueUp enable/disable
  - visible workout data tiles (up to 8)
- Persist settings through existing settings storage
- Integrate settings screen into the main window navigation/tabs
- Remove tile selection controls from `ui/workout_screen.py` and keep the workout page focused on display/control only

### Acceptance Criteria
- Settings values persist between app restarts.
- Workout screen reflects tile visibility configured in Settings.
- Tile selection is no longer editable on the workout page.

### Suggested Codex prompt
â€œImplement Task 09.5: add a Settings screen and move workout tile selection UI from Workout to Settings, keeping persistence and limiting selections to 8.â€

---

## Task 10 - FTMS control: ERG target power + resistance level (STATUS: DONE)

### Goal
Implement sending FTMS control commands for ERG (target power) and resistance mode (resistance level).

### Deliverables
- `core/control/ftms_control.py`
- Control API:
  - `set_erg_target_watts(watts)`
  - `set_resistance_level(percent_or_unit)`
  - `set_mode_erg()`, `set_mode_resistance()` (as needed per trainer)
- Robust ack/timeouts and error reporting

### Acceptance Criteria
- Interval change triggers control command.
- Pause sets ERG=0W or resistance=0% based on current mode.
- Errors surfaced to UI alert channel (stub ok).

### Suggested Codex prompt
â€œImplement Task 10: FTMS control point write logic for ERG target power and resistance level with ack/timeouts. Integrate with workout engine state updates.â€

---

## Task 11 - Hybrid mode logic (ERG recovery / resistance work) (STATUS: DONE)

### Goal
Implement Hybrid mode per spec:
- Recovery (<56% FTP): ERG
- Work (>=56% FTP): Resistance, remember last set resistance during workout

### Deliverables
- `core/control/hybrid_mode.py`
- Resistance jog hotkeys (Up/Down 1%, Left/Right 5%) in work intervals
- Session memory for work resistance level

### Acceptance Criteria
- Seamless mode switch at interval boundaries.
- Resistance level persists across work intervals within the workout.
- User can jog resistance level and see it reflected live.

### Suggested Codex prompt
Implement Task 11: Hybrid mode switching and resistance jog controls, with session memory for resistance in work intervals. Add tests for interval transitions.â€

---

## Task 12 - OpenTrueUp (offset-based) (STATUS: TODO)

### Goal
Implement OpenTrueUp:
- 30s moving average
- update every 5s
- offset = bikePM avg - trainer avg
- apply offset to ERG target
- persist offset per trainer+PM pair
- dropout handling (>3s missing PM)

### Deliverables
- `core/control/opentrueup.py`
- Persistence in `storage/opentrueup_offsets.py`
- UI visibility toggle and value display (optional; can be minimal)

### Acceptance Criteria
- Offset updates only when changed.
- Offset applied to ERG target (not in resistance mode).
- Offset still computed in background while in resistance mode.
- Dropout behavior matches spec.

### Suggested Codex prompt
Implement Task 12: OpenTrueUp module with persistence and dropout handling, and integrate into ERG control path. Add unit tests using simulated sensor streams.â€

---

## Task 13 - Hotkeys (global) per spec (STATUS: TODO)

### Goal
Implement hotkeys:
- T toggle mode
- 1/5 extend interval (or kJ)
- Tab skip interval
- Arrows jog %FTP/resistance
- Space pause/resume

### Deliverables
- `ui/hotkeys.py` and integration into Workout screen
- Tests (where feasible) and manual testing checklist

### Acceptance Criteria
- Hotkeys work on workout screen without interfering with text fields.
- Correct behavior in time vs kJ mode (kJ can be stub until implemented).

### Suggested Codex prompt
Implement Task 13: hotkeys per spec on the workout screen. Ensure no blocking and avoid intercepting input when user is typing.

---

## Task 14 - Packaging: Flatpak (STATUS: DONE)

### Goal
Create Flatpak manifest suitable for BLE + file export.

### Deliverables
- `flatpak/` manifest
- Permissions for BlueZ/system bus access and filesystem export target
- Build instructions

### Acceptance Criteria
- Flatpak builds and launches.
- BLE scan works (requires appropriate permissions).
- FIT export writes to allowed location.

### Suggested Codex prompt
Implement Task 14: Flatpak packaging manifest and build instructions, including required permissions for BLE (BlueZ) and file export. Keep manifest minimal.

---

## Task 15 - Packaging: Windows MSI (STATUS: DONE)

### Goal
Produce Windows installer output.

### Deliverables
- Packaging config (e.g., PyInstaller + MSI toolchain)
- Build instructions

### Acceptance Criteria
- MSI installs and runs.
- Settings/storage paths correct.
- BLE scan works.

### Suggested Codex prompt
â€œImplement Task 15: Windows packaging to MSI using a free toolchain (PyInstaller + MSI builder). Provide build steps and ensure app runs after install.â€

---

## Notes / Deferred Work
- `.octw` formal schema versioning (placeholder in spec)
- kJ-mode full implementation beyond hooks
- RR intervals / DFA1alpha
- API uploads (intervals.icu / Strava / Garmin)
- Localization beyond US English

"""
spec_path.write_text(content, encoding="utf-8")

str(spec_path)



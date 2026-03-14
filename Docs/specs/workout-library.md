# Workout Library — Feature Spec

## Overview
Add a Workout Library tab that lets users browse, search, and load workouts. Replaces the single "Load Workout" button on the main screen with two separate entry points.

---

## Storage

| Source | Location |
|---|---|
| User-added workouts | Windows: `%APPDATA%\OpenCycleTrainer\workouts\` / Linux: `~/.local/share/opencycletrainer/workouts/` |
| Prepackaged workouts | App install directory `workouts/` subdirectory |

Both directories are scanned when the library is opened. No automatic copying of prepackaged workouts to APPDATA is required.

---

## Main Screen Changes

The existing "Load Workout" button is replaced with two stacked buttons (From Library on top):

- **Load Workout From Library** — navigates to the Workout Library tab
- **Load Workout From File** — opens a file picker (existing behavior, unchanged)

---

## Workout Library Tab

A new top-level tab at the same level as Devices and Settings.

### Workout List

| Column | Value |
|---|---|
| Name | Filename without extension |
| Duration | Total duration parsed from MRC file data |

- Sortable by Name and Duration (click column header to toggle asc/desc)
- Default sort: Name ascending

### Search

- Text input that filters the list by name as the user types (case-insensitive, substring match)
- Clears to show all workouts when empty

### Add to Library

- A button on the library screen opens a file picker
- Selected file is copied into the user workouts directory (`%APPDATA%\OpenCycleTrainer\workouts\` / Linux equivalent)
- List refreshes after copy

### Loading a Workout

- Double-clicking a row loads that workout into the main screen and navigates to the main tab

---

## Out of Scope

- Editing or deleting workouts from the library
- Workout metadata beyond name and duration
- Subfolders / categories
- Copying prepackaged workouts to APPDATA on first run

---

## Implementation Phases

### Phase 1 — Storage Paths

**Goal:** Establish platform-aware paths for user and prepackaged workout directories.

**Files:**
- `opencycletrainer/storage/paths.py` — add `user_workouts_dir()` and `prepackaged_workouts_dir()` functions; `user_workouts_dir()` must create the directory if it doesn't exist (same pattern as existing path helpers)
- `workouts/` — create this subdirectory at the repo root; it will serve as the prepackaged workouts location in development and the install directory at runtime
- `opencycletrainer/tests/test_paths.py` — add tests for both new path helpers (existence, correct platform roots)

**Acceptance:** Both paths resolve correctly on Windows and Linux. User workouts dir is created on first call.

---

### Phase 2 — Workout Library Model

**Goal:** A backend class that scans both directories, parses each MRC file for its duration, and supports copying a file into the user library.

**Files:**
- `opencycletrainer/core/workout_library.py` — new module
  - `WorkoutLibraryEntry(name: str, path: Path, duration_seconds: int)` — plain dataclass
  - `WorkoutLibrary` — loads entries from both dirs via `MrcParser`; exposes `entries: list[WorkoutLibraryEntry]`, `refresh()`, and `add_workout(source_path: Path) -> WorkoutLibraryEntry`
  - Duration is total workout duration derived from the parsed `Workout` object (`workout.intervals[-1].end_offset_seconds`)
  - Files that fail to parse are silently skipped (logged at WARNING level)
- `opencycletrainer/tests/test_workout_library.py` — new test module
  - Use `tmp_path` fixture for both dirs; seed with sample MRC files from `tests/data/`
  - Test: entries populated from both dirs, duplicates (same filename in both) show both, `add_workout` copies file and appears in `entries` after `refresh()`, unparseable files are skipped

**Acceptance:** All tests pass. No changes to existing files in this phase.

---

### Phase 3 — Main Screen Button Swap

**Goal:** Replace the single "Load Workout" button with two stacked buttons.

**Files:**
- `opencycletrainer/ui/workout_screen.py` — replace the existing load button widget with a `QVBoxLayout` containing two `QPushButton`s: `"Load from Library"` (`load_from_library_button`) on top, `"Load from File"` (`load_from_file_button`) below
- `opencycletrainer/ui/workout_controller.py` — disconnect old button; wire `load_from_file_button` to the existing file-picker logic (currently on the old button); leave `load_from_library_button` connected to a `load_from_library_requested` signal that the main window will handle in Phase 5
- `opencycletrainer/tests/test_workout_controller.py` — update any tests that reference the old button name; add test that clicking `load_from_file_button` still triggers the file dialog

**Acceptance:** File-picker behavior is unchanged. Library button exists but navigation is a no-op until Phase 5.

---

### Phase 4 — Workout Library Tab UI

**Goal:** A new tab widget with the full library UI: table, search, and add button.

**Files:**
- `opencycletrainer/ui/workout_library_screen.py` — new module
  - `WorkoutLibraryScreen(QWidget)` — accepts a `WorkoutLibrary` instance
  - `QTableWidget` with columns Name and Duration (formatted as `h:mm:ss`); rows populated from `library.entries`
  - Column headers are clickable to sort asc/desc; default sort is Name ascending
  - `QLineEdit` search bar above the table; filters rows case-insensitively on `textChanged`
  - `"Add to Library"` button — opens `QFileDialog` (MRC filter), calls `library.add_workout()`, calls `refresh()`
  - Double-click on a row emits `workout_selected = Signal(Path)` with the entry's path
- `opencycletrainer/ui/main_window.py` — instantiate `WorkoutLibrary` and `WorkoutLibraryScreen`; add as a tab labelled `"Library"` between the existing Workout and Devices tabs
- `opencycletrainer/tests/test_workout_library_screen.py` — new test module
  - Seed `WorkoutLibrary` with temp MRC files; verify rows appear, search filters correctly, sort toggles, `workout_selected` signal fires on double-click

**Acceptance:** Library tab is visible and functional. Double-click fires the signal (not yet wired to load).

---

### Phase 5 — Integration Wiring

**Goal:** Connect the library tab and main screen buttons end-to-end so the full user flow works.

**Files:**
- `opencycletrainer/ui/main_window.py`
  - Connect `workout_library_screen.workout_selected` → call `workout_controller.load_workout(path)` → switch to the Workout tab
  - Connect `workout_screen.load_from_library_button` (via `workout_controller`'s signal) → switch to the Library tab
- `opencycletrainer/ui/workout_controller.py` — expose `load_workout(path: Path)` as a public method (extract from existing file-dialog handler) so it can be called from the main window without a dialog
- `opencycletrainer/tests/test_workout_controller.py` — add test that `load_workout(path)` loads the workout without opening a dialog

**Acceptance:** Full flow works — "Load from Library" navigates to the Library tab, double-clicking a row loads the workout and returns to the Workout tab. "Load from File" still opens a file picker. All existing tests continue to pass.

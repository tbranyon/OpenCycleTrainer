# Open Items

1. .octw internal format support is not implemented (no parser/writer/schema in code).
2. kJ-based workout completion is not implemented (engine explicitly marks kJ mode as stub). Evidence: workout_engine.py.
3. CI build pipelines for Windows/Linux are not present in repo (no workflow configuration found).
4. `extend_interval()` in `workout_engine.py` has no upper bound on the extension value. A misbehaving caller could extend an interval to an unreasonable duration. Add a reasonable cap or validation.
5. No end-to-end integration test covering the full workout loop: load workout -> start -> tick -> finish -> FIT file written. Add at least one such test to catch wiring regressions between engine, recorder, and exporter.
6. **Interval transition audio alerts.** Play an audible cue shortly before and at the moment of each interval change, so users don't need to watch the screen during hard efforts.
    - Add an "alert seconds before interval" setting to `AppSettings` (e.g. default 3s, range 0-10s; 0 = disabled). Expose it in the Settings tab.
    - In the workout engine tick (or `WorkoutSessionController`), detect when remaining interval time crosses the configured threshold and when it reaches 0 (transition). Emit a distinct signal for each event - e.g. `interval_warning` and `interval_changed`.
    - In `WorkoutScreen`, connect those signals to a sound-playback slot using PySide6's `QSoundEffect`. Bundle two short audio clips (warning beep, transition chime) in `res/`. Fall back gracefully if audio is unavailable (log a warning, do not crash).
    - Ensure alerts don't fire spuriously on pause/resume or when skipping intervals manually.
7. Add a field to the Builder to add a description to the workout. Read these descriptions out on the right pane in the workout Library when viewing workouts. (Using the standard description field for both MRC and ZWO files)
8. **Dispose of screens and dialogs in tests.** Workout screens and main windows are now deleted after each test (`dispose_workout_screens` and `dispose_main_windows` in `tests/conftest.py`), and the run ends with a "Qt windows still alive" summary listing what tests still leave behind. Still to do, checking the suite several times after each step, since the crashes this guards against are rare:
    - Dialogs and standalone widgets: course import/split/lap dialogs, `SettingsScreen`, `DevicesScreen`, `WorkoutChartWidget`, `CourseMapWidget`/`CourseMapPanel`.
    - Find where the ~1500 leftover `QMenu`s (and the `QFrame`/`QWidget`/`ViewBoxMenu` windows) come from; probably pyqtgraph's right-click menus, which are created without a parent and may also pile up in the app each time a plot is rebuilt.
    - Once the summary is empty (or lists only harmless objects), remove the `os._exit` in `pytest_unconfigure`.
9. BLE reconnect briefly reports a device as connected while still flagged as connecting and reconnecting: `_connect_once` in `ble_backend.py` marks it connected before the connect task and reconnect loop clear their flags. The Devices screen can show "Reconnecting…" next to a connected device for a moment, and `test_ble_connections.py::test_dropped_device_shows_reconnecting_then_comes_back` fails about one run in five because it checks in that gap. Clear the flags before (or together with) marking the device connected.

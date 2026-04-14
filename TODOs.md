# Open Items

1. .octw internal format support is not implemented (no parser/writer/schema in code).
2. kJ-based workout completion is not implemented (engine explicitly marks kJ mode as stub). Evidence: workout_engine.py.
3. Primary power source selection logic and persistence per pairing are not implemented.
4. CI build pipelines for Windows/Linux are not present in repo (no workflow configuration found).
5. Errors in FTMS layer prevent writing FIT file on Stop apparently (sometimes). FIT file should be written on stop regardless of state.
6. Double clicking a connected device in the device list should fetch and display its capabilities (as reported by its relevant service characteristics, but transposed to human-readable form) in a modal. 6a. [DONE] ~~FTMS trainers~~, 6b. CPS Power Meters, 6c. [DONE] ~~Heart Rate Monitors~~
7. [DONE] ~~BLE backend test pollution: forgetting to pass a mock `PairedDeviceStore` in tests writes to real user data files. Add a runtime guard (e.g., raise if the default production path is used without an explicit opt-in) rather than relying on developer discipline.~~
8. `WorkoutSessionController` is growing too complex — it tracks power history, cadence history, per-interval stats, mode state, and OpenTrueUp state all in one class. Decompose into smaller focused objects to improve testability and maintainability.
9. [DONE] ~~`except Exception` in `workout_library.py` is too broad when skipping unparseable files. Narrow to specific parser exception types to avoid swallowing import errors, OOM, or other unexpected failures.~~
10. [DONE] ~~`_manual_resistance_offset_percent = 33.0` in `workout_controller.py` is an unexplained magic number used when switching modes. Extract to a named constant and add a comment explaining the intent.~~
11. [DONE] ~~Resistance level range can be `None` in `ftms_control.py` for trainers that don't report it. Add an explicit fallback or guard so behavior is defined rather than undefined in that case.~~
12. [DONE] ~~Thread safety in `AsyncioRunner`: `_closed` flag is not atomic and `_loop` can be `None` during startup/shutdown edge cases. Guard against race conditions if shutdown is called from multiple threads.~~
13. [DONE] ~~`AppSettings.from_dict()` restores `last_workout_dir`/`workout_data_dir` as `Path` objects without checking whether those paths still exist. Add existence validation on restore.~~
14. `extend_interval()` in `workout_engine.py` has no upper bound on the extension value. A misbehaving caller could extend an interval to an unreasonable duration. Add a reasonable cap or validation.
15. No end-to-end integration test covering the full workout loop: load workout → start → tick → finish → FIT file written. Add at least one such test to catch wiring regressions between engine, recorder, and exporter.
16. Recent free ride activity would not write anything to the trainer, neither resistance or ERG worked. Launching a workout in ERG worked correctly though.
17. [DONE] ~~Cadence should be smoothed to 1s on display and ignore drop-outs for up to 3s.~~
18. Need some error handling/reporting/timeout logic for Strava sync. Sync was attempted but nothing ever completed. Eventually I got an error message but it took minutes. This should be maybe 30s absolute max. 18b) [DONE] ~~Part of this sync issue might be bad FIT file structure/data. When I try to manually upload the FIT, Strava can't get past "Analzying...". If I run the FIT through fitfileviewer.com I can repair it and then it uploads. The notes I get from the viewer/repair process are: "    Some Session messages are missing or invalid: Invalid messages are marked in red, missing messages are added and displayed in blue in the tables below.
    The Activity message is invalid or a valid activity messages is missing: Invalid messages are marked in red, missing messages are added and displayed in blue in the tables below.

"~~
19. Resistance mode with the Saris H3 still appears to not work.
20. [DONE] ~~FIT file timestamp is way off. I rode at ~9:20-9:30PM (my time, CDT)  for 30 min. and once uploaded to Strava it showed that I rode at 2:20AM.~~
21. **Interval transition audio alerts.** Play an audible cue shortly before and at the moment of each interval change, so users don't need to watch the screen during hard efforts.
    - Add an "alert seconds before interval" setting to `AppSettings` (e.g. default 3s, range 0–10s; 0 = disabled). Expose it in the Settings tab.
    - In the workout engine tick (or `WorkoutSessionController`), detect when remaining interval time crosses the configured threshold and when it reaches 0 (transition). Emit a distinct signal for each event — e.g. `interval_warning` and `interval_changed`.
    - In `WorkoutScreen`, connect those signals to a sound-playback slot using PySide6's `QSoundEffect`. Bundle two short audio clips (warning beep, transition chime) in `res/`. Fall back gracefully if audio is unavailable (log a warning, do not crash).
    - Ensure alerts don't fire spuriously on pause/resume or when skipping intervals manually.
    - Consider also flashing the existing alert banner with the upcoming interval's power target as a visual accompaniment.
22. **Per-interval breakdown in the post-workout summary.** Append a scrollable table to `WorkoutSummaryDialog` showing how the user performed against each interval target — the key "did I hit my numbers?" question that structured training demands.
    - During the workout, `WorkoutSessionController` already tracks per-interval avg power and avg HR. Ensure interval start/end timestamps, target power (watts and %FTP), actual avg power, and avg HR are captured per interval into a list of interval result objects. Also track whether the interval was skipped.
    - After workout stop/finish, pass the interval result list into `WorkoutSummaryDialog` alongside the existing aggregate stats.
    - Render a `QTableWidget` (or equivalent) below the existing summary tiles with columns: #, Duration, Target (W), Actual Avg (W), % of Target, Avg HR. Color-code the % of Target cell: ≥95% green, 85–94% yellow, <85% red. Skip skipped intervals or mark them visually.
    - Free-ride intervals (no power target) should show "—" in the target/% columns.
    - Make the table section collapsible or scrollable so the dialog stays manageable for long workouts with many intervals.
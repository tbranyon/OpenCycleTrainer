# Open Items

1. .octw internal format support is not implemented (no parser/writer/schema in code).
2. kJ-based workout completion is not implemented (engine explicitly marks kJ mode as stub). Evidence: workout_engine.py.
3. Primary power source selection logic and persistence per pairing are not implemented.
4. CI build pipelines for Windows/Linux are not present in repo (no workflow configuration found).
5. Double clicking a connected device in the device list should fetch and display its capabilities (as reported by its relevant service characteristics, but transposed to human-readable form) in a modal. 6a. [DONE] ~~FTMS trainers~~, 6b. CPS Power Meters, 6c. [DONE] ~~Heart Rate Monitors~~
6. `extend_interval()` in `workout_engine.py` has no upper bound on the extension value. A misbehaving caller could extend an interval to an unreasonable duration. Add a reasonable cap or validation.
7. No end-to-end integration test covering the full workout loop: load workout → start → tick → finish → FIT file written. Add at least one such test to catch wiring regressions between engine, recorder, and exporter.
8. Recent free ride activity would not write anything to the trainer, neither resistance or ERG worked. Launching a workout in ERG worked correctly though.
9. Resistance mode with the Saris H3 still isn't quite right -- switching to resistance mode provides a VERY HIGH resistance that doesn't seem to change when resistance is modified through the UI. It's certainly not the same "33%" default that TrainerRoad provides on the same trainer.
10. **Interval transition audio alerts.** Play an audible cue shortly before and at the moment of each interval change, so users don't need to watch the screen during hard efforts.
    - Add an "alert seconds before interval" setting to `AppSettings` (e.g. default 3s, range 0–10s; 0 = disabled). Expose it in the Settings tab.
    - In the workout engine tick (or `WorkoutSessionController`), detect when remaining interval time crosses the configured threshold and when it reaches 0 (transition). Emit a distinct signal for each event — e.g. `interval_warning` and `interval_changed`.
    - In `WorkoutScreen`, connect those signals to a sound-playback slot using PySide6's `QSoundEffect`. Bundle two short audio clips (warning beep, transition chime) in `res/`. Fall back gracefully if audio is unavailable (log a warning, do not crash).
    - Ensure alerts don't fire spuriously on pause/resume or when skipping intervals manually.
    - Consider also flashing the existing alert banner with the upcoming interval's power target as a visual accompaniment.
11. **Per-interval breakdown in the post-workout summary.** Append a scrollable table to `WorkoutSummaryDialog` showing how the user performed against each interval target — the key "did I hit my numbers?" question that structured training demands.
    - During the workout, `WorkoutSessionController` already tracks per-interval avg power and avg HR. Ensure interval start/end timestamps, target power (watts and %FTP), actual avg power, and avg HR are captured per interval into a list of interval result objects. Also track whether the interval was skipped.
    - After workout stop/finish, pass the interval result list into `WorkoutSummaryDialog` alongside the existing aggregate stats.
    - Render a `QTableWidget` (or equivalent) below the existing summary tiles with columns: #, Duration, Target (W), Actual Avg (W), % of Target, Avg HR. Color-code the % of Target cell: ≥95% green, 85–94% yellow, <85% red. Skip skipped intervals or mark them visually.
    - Free-ride intervals (no power target) should show "—" in the target/% columns.
    - Make the table section collapsible or scrollable so the dialog stays manageable for long workouts with many intervals.
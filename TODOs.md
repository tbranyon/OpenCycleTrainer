# Open Items

1. .octw internal format support is not implemented (no parser/writer/schema in code).
2. kJ-based workout completion is not implemented (engine explicitly marks kJ mode as stub). Evidence: workout_engine.py.
3. CI build pipelines for Windows/Linux are not present in repo (no workflow configuration found).
4. Double clicking a connected device in the device list should fetch and display its capabilities (as reported by its relevant service characteristics, but transposed to human-readable form) in a modal. 6a. [DONE] ~~FTMS trainers~~, 6b. CPS Power Meters, 6c. [DONE] ~~Heart Rate Monitors~~
5. `extend_interval()` in `workout_engine.py` has no upper bound on the extension value. A misbehaving caller could extend an interval to an unreasonable duration. Add a reasonable cap or validation.
6. No end-to-end integration test covering the full workout loop: load workout -> start -> tick -> finish -> FIT file written. Add at least one such test to catch wiring regressions between engine, recorder, and exporter.
7. **Interval transition audio alerts.** Play an audible cue shortly before and at the moment of each interval change, so users don't need to watch the screen during hard efforts.
    - Add an "alert seconds before interval" setting to `AppSettings` (e.g. default 3s, range 0-10s; 0 = disabled). Expose it in the Settings tab.
    - In the workout engine tick (or `WorkoutSessionController`), detect when remaining interval time crosses the configured threshold and when it reaches 0 (transition). Emit a distinct signal for each event - e.g. `interval_warning` and `interval_changed`.
    - In `WorkoutScreen`, connect those signals to a sound-playback slot using PySide6's `QSoundEffect`. Bundle two short audio clips (warning beep, transition chime) in `res/`. Fall back gracefully if audio is unavailable (log a warning, do not crash).
    - Ensure alerts don't fire spuriously on pause/resume or when skipping intervals manually.
    - Consider also flashing the existing alert banner with the upcoming interval's power target as a visual accompaniment.
8. Strava upload
    - Image upload doesn't appear to work. Tested from installed flatpak, so didn't get to see log output. Either didn't work or it's very large so took > 5 minutes to upload or was rejected.
    - Captured image in png folder looks bad. We should rescale the plot to fill the x-axis (e.g. in free ride where the user may have a large empty span on the x-axis when they stop).
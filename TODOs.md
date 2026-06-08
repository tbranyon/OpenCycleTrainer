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
7. ~~Resistance mode works properly in Free Ride, but seems to go to 100% resistance regardless of user setting in a workout~~ ✓ Fixed: `FTMSBridgeManager` now passes `manual_resistance_level` to the bridge for all non-free-ride Resistance mode paths.
8. Pause should suspend plot updates and really any data recording. Currently, pause continues to plot and then jumps back to the last legit time and starts plotting again, without erasing the "data" captured during pause
9. Workout names as edited/saved in the post workout modal should be populated to the Strava upload. The datetime stamp added to the filename should not be appended to Strava activities.
10. Add a setting to toggle between power target jogs either being for the life of the current interval only vs. modifying the setpoint persistently across the whole workout
11. Add the ability to edit workouts from the library (using the Builder) and either save edits (overwrite) or save as a new workout
12. Add support for predefined blocks like "warmup" and "cooldown" that the user can define and then reference from the workout builder, so a user can for example define a standard warmup profile and easily add it to every workout they build.
13. Add a text cue to the Builder pane instructing the user about the "!" skip last recovery interval syntax
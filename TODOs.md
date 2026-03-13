# Open Items

1. .octw internal format support is not implemented (no parser/writer/schema in code).
2. kJ-based workout completion is not implemented (engine explicitly marks kJ mode as stub). Evidence: workout_engine.py.
3. Free Ride behavior is not implemented beyond a settings enum (no free-ride control logic/manual target workflow).
4. Pause/resume ramp-in countdown user messaging is missing in UI.
5. [DONE] ~~Live workout charts are not implemented (explicit TODO placeholders). Evidence: workout_screen.py.~~
6. [DONE] ~~Live metric computation/refresh for tiles is not implemented (tiles render, but no data-update path).~~
7. [DONE] ~~Workout completion summary screen (“Great job!” with time/kJ/NP/TSS/avg HR) is not implemented.~~
8. Primary power source selection logic and persistence per pairing are not implemented.
9. [DONE] ~~Device pairing persistence is not implemented (pair state is in-memory backend state, not saved to storage).~~
10. [DONE] ~~OpenTrueUp is implemented as a module, but not integrated into runtime app flow/settings wiring (offset display method exists but is not fed by app logic). Evidence: opentrueup.py, workout_screen.py.~~
11. [DONE] ~~Recorder/FIT export are implemented modules but not wired to workout lifecycle in the running app.~~
12. Display units/date/time formatting behavior from spec is not implemented in UI behavior.
13. CI build pipelines for Windows/Linux are not present in repo (no workflow configuration found).
14. [DONE] ~~Graphs should load with workout file (currently don't display until workout is started)~~
15. Switch to resistance mode doesn't work (FTMS command failure)
16. [DONE] ~~Need current target power on display - mandatory field~~
17. Need to do something when an interval is skipped--truncate the graph and put a yellow bar at the skip point
18. Elapsed time shouldn't advance on skip
19. [POSSIBLY DONE, NEEDS REAL TEST] ~~Calibrate doesn't seem to work quite right, no light on PM~~
20. [DONE] ~~Device pairings didn't seem to persist between invocations~~
21. [DONE] ~~Don't seem to release devices correctly, closing the application left the devices connected and couldn't be re-found on subsequent invocations, status lights on devices indicated they're still connected to something.~~
22. [DONE] ~~Need to display current resistance level when in resistance mode~~
23. Errors in FTMS layer prevent writing FIT file on Stop apparently (sometimes). FIT file should be written on stop regardless of state.
24. [DONE] ~~FIT file write message should be in green, not red.~~
25. Add workout library tab/screen which lists all workouts both added by the user and prepackaged with the app. User should be able to load a workout from this screen by double clicking.
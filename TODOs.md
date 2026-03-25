# Open Items

1. .octw internal format support is not implemented (no parser/writer/schema in code).
2. kJ-based workout completion is not implemented (engine explicitly marks kJ mode as stub). Evidence: workout_engine.py.
3. Free Ride behavior is not implemented beyond a settings enum (no free-ride control logic/manual target workflow).
4. [DONE] ~~Pause/resume ramp-in countdown user messaging is missing in UI.~~
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
17. [DONE] ~~Need to do something when an interval is skipped--truncate the graph and put a yellow bar at the skip point~~
18. [DONE] ~~Elapsed time shouldn't advance on skip~~
19. [DONE] ~~Calibrate doesn't seem to work quite right, no light on PM~~
20. [DONE] ~~Device pairings didn't seem to persist between invocations~~
21. [DONE] ~~Don't seem to release devices correctly, closing the application left the devices connected and couldn't be re-found on subsequent invocations, status lights on devices indicated they're still connected to something.~~
22. [DONE] ~~Need to display current resistance level when in resistance mode~~
23. Errors in FTMS layer prevent writing FIT file on Stop apparently (sometimes). FIT file should be written on stop regardless of state.
24. [DONE] ~~FIT file write message should be in green, not red.~~
25. [DONE] ~~Add workout library tab/screen which lists all workouts both added by the user and prepackaged with the app. User should be able to load a workout from this screen by double clicking.~~
26. [DONE] ~~Power jog adjustments need to persist for the remainder of the interval. They currently seem to get overwritten after a moment~~
27. [DONE] ~~Ramp doesn't work with Tempo 1x15 at least, just maintained the start power. Switching between resistance and back to ERG jumped to the current ramp target momentarily but then got overwritten again with original start power.~~
28. [DONE] ~~Need cadence tile on display~~
29. [DONE] ~~Error alerts should not persist indefinitely on the UI. They should be clearable and auto clear after 5s.~~
30. [DONE] ~~Strava sync Phases 1-4: OAuth connect/disconnect, secure token storage, and automatic FIT upload on workout completion.~~
31. [DONE] ~~Strava sync Phase 5: Structured logging, duplicate upload prevention with local history, external_id on uploads, "already synced" alert, and Sync Now button wiring.~~
32. [DONE] ~~Strava sync Phase 6: workout power chart image generated (matplotlib, 1080×1350 portrait) and attached to Strava activity after successful FIT upload, best-effort and non-blocking.~~
33. Configure plots - Allow user to disable interval plot in Settings. If disabled, whole-workout plot should fill up its space.
34. [DONE] ~~Cursor continues to advance on charts while paused. There also appears to be a 3-second countdown on the pause modal followed by a 3-second ramp in once returned from the modal--the correct sequence should be to do the ramp-in with the 3 second countdown on the pause modal.~~
35. [DONE] ~~Settings and value changes on the Settings page should automatically be saved when changed, rather than requiring the user to click Save.~~
36. [DONE] ~~OpenTrueUp enable should be grayed out whenever the user does not have both a power meter and a power-reporting trainer connected~~
37. UI should show some indication that auto-reconnecting devices are in the process of connecting.
38. [DONE] ~~Mock backend should only be a programmatic option for test scripts, the UI should not expose a backend toggle and should always use Bleak whenever we are not testing.~~
39. [DONE] ~~Remove the display units toggle in settings, nothing uses it~~
40. The Target Power tile should be modified to show "Current / Target Power" as the title and the values shown respectively (i.e. 151 / 153 W) in the box. This should use windowed average power for the current power, and Windowed Average Power should be removed from the configurable tile list.
41. [DONE] ~~Remove "Default workout behavior" from the settings screen. This will be handled in other ways later.~~
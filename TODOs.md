# Open Items
The following items are described in the spec but not presently implemented.  
  
1. No end-to-end workout execution pipeline in the app UI (workout signals are emitted but not wired to engine/control/recorder). Evidence: workout_screen.py, main_window.py, app.py.  

2. No workout import flow in the UI (MRC parser exists, but no file-load path in app screens). Evidence: mrc_parser.py, workout_screen.py.  

3. .octw internal format support is not implemented (no parser/writer/schema in code).
4. kJ-based workout completion is not implemented (engine explicitly marks kJ mode as stub). Evidence: workout_engine.py.
5. Free Ride behavior is not implemented beyond a settings enum (no free-ride control logic/manual target workflow).
6. Lead-time behavior is not implemented in control/execution (lead-time is stored in settings only). Evidence: settings.py.
7. Pause/resume ramp-in countdown user messaging is missing in UI.
8. Live workout charts are not implemented (explicit TODO placeholders). Evidence: workout_screen.py.
9. Live metric computation/refresh for tiles is not implemented (tiles render, but no data-update path).
10. Workout completion summary screen (“Great job!” with time/kJ/NP/TSS/avg HR) is not implemented.
11. Primary power source selection logic and persistence per pairing are not implemented.
12. Device pairing persistence is not implemented (pair state is in-memory backend state, not saved to storage).
13. Real BLE zero-offset calibration command is not implemented (Bleak backend returns False). Evidence: ble_backend.py.
14. OpenTrueUp is implemented as a module, but not integrated into runtime app flow/settings wiring (offset display method exists but is not fed by app logic). Evidence: opentrueup.py, workout_screen.py.
15. Recorder/FIT export are implemented modules but not wired to workout lifecycle in the running app.
16. Display units/date/time formatting behavior from spec is not implemented in UI behavior.
17. CI build pipelines for Windows/Linux are not present in repo (no workflow configuration found).
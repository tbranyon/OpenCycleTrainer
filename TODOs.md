# Open Items
The following items are described in the spec but not presently implemented.  

1. .octw internal format support is not implemented (no parser/writer/schema in code).
2. kJ-based workout completion is not implemented (engine explicitly marks kJ mode as stub). Evidence: workout_engine.py.
3. Free Ride behavior is not implemented beyond a settings enum (no free-ride control logic/manual target workflow).
4. Pause/resume ramp-in countdown user messaging is missing in UI.
5. Live workout charts are not implemented (explicit TODO placeholders). Evidence: workout_screen.py.
6. [DONE] Live metric computation/refresh for tiles is not implemented (tiles render, but no data-update path).
7. Workout completion summary screen (“Great job!” with time/kJ/NP/TSS/avg HR) is not implemented.
8. Primary power source selection logic and persistence per pairing are not implemented.
9. Device pairing persistence is not implemented (pair state is in-memory backend state, not saved to storage).  
10. [DONE] OpenTrueUp is implemented as a module, but not integrated into runtime app flow/settings wiring (offset display method exists but is not fed by app logic). Evidence: opentrueup.py, workout_screen.py.
11. [DONE] Recorder/FIT export are implemented modules but not wired to workout lifecycle in the running app.
12. Display units/date/time formatting behavior from spec is not implemented in UI behavior.
13. CI build pipelines for Windows/Linux are not present in repo (no workflow configuration found).
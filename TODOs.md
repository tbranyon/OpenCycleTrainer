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

# OpenCycleTrainer Architecture Diagram

This diagram documents how control commands, live telemetry, recording, workout
authoring, course rides and DFA α1 route through the project modules.

## Control Command Routing (UI -> Trainer)

```mermaid
flowchart TD
    rider((Rider))

    subgraph UI[UI Layer]
        hotkeys[WorkoutHotkeys]
        workout_screen[WorkoutScreen]
        devices_screen[DevicesScreen]
        main_window[MainWindow]
    end

    subgraph Controller[WorkoutSessionController]
        controller[WorkoutSessionController]
        engine[WorkoutEngine]
        mode_state[ModeState]
        ot_state[OpenTrueUpState]
        bridge_mgr[FTMSBridgeManager]
    end

    subgraph BridgeThread[Trainer Control executor thread]
        bridge[WorkoutEngineFTMSBridge]
        opentrueup[OpenTrueUpController]
        ftms_control[FTMSControl]
    end

    subgraph BLE[BLE Transport]
        ftms_transport[BleakFTMSControlTransport]
        ble_backend[BleakDeviceBackend]
        trainer[(Smart Trainer FTMS CP)]
    end

    rider --> hotkeys
    rider --> workout_screen
    hotkeys --> workout_screen
    workout_screen -->|start/pause/resume/end/extend/skip/jog/mode/load/free-ride/erg-target signals| controller
    controller -->|engine commands| engine
    engine -->|snapshots| controller
    devices_screen -->|trainer_device_changed| main_window
    main_window -->|set_trainer_control_target| controller
    controller -->|active control mode / jog / resistance| mode_state
    controller -->|submit_snapshot / submit_action| bridge_mgr
    bridge_mgr -->|executor-queued actions| bridge
    bridge --> opentrueup
    ot_state -.shares controller.-> opentrueup
    bridge -->|ERG target W / resistance level %| ftms_control
    ftms_control --> ftms_transport
    ftms_transport --> ble_backend
    ble_backend -->|gatt write + indication ack| trainer
```

## Telemetry Routing (Devices -> UI)

```mermaid
flowchart TD
    subgraph Sources[Device Sources]
        trainer[(Trainer FTMS)]
        pm[(Power Meter CPS)]
        hr[(HR Sensor HRS)]
        csc[(Cadence/Speed CSC)]
    end

    subgraph BLEStack[BLE + Decode]
        device_manager[DeviceManager / BleakDeviceBackend]
        devices_screen[DevicesScreen]
        decoders[Protocol Decoders ftms/cps/hrs/csc]
        sensor_sample[SensorSample]
    end

    subgraph App[Application]
        main_window[MainWindow _on_sensor_sample]
        controller[WorkoutSessionController receive_*]
        bridge_mgr[FTMSBridgeManager]
        workout_screen[WorkoutScreen tiles/charts]
    end

    trainer --> device_manager
    pm --> device_manager
    hr --> device_manager
    csc --> device_manager
    device_manager -->|GATT notifications| devices_screen
    devices_screen --> decoders
    decoders --> sensor_sample
    sensor_sample -->|signal: sensor_sample_received| main_window
    main_window -->|receive_power_watts / bike_power_watts / hr_bpm / rr_intervals_ms / cadence_rpm / speed_mps / pedal_balance / bike_energy_kj / trainer_energy_kj| controller
    controller -->|live power samples| bridge_mgr
    bridge_mgr -->|OpenTrueUp offset / ERG re-apply| controller
    controller -->|live metrics / charts / offset| workout_screen
```

## Recording/Export Routing (Controller -> Storage/Cloud)

```mermaid
flowchart TD
    controller[WorkoutSessionController]
    rec_integration[RecorderIntegration]
    aggregator[OneSecondAggregator]
    recorder[WorkoutRecorder]
    fit_exporter[FitExporter]
    workout_screen[WorkoutScreen]
    strava[Strava Sync Service]
    icu[intervals.icu Sync Service]
    manual_save[Manual save: WorkoutRecorder + FitExporter]

    samples[(samples.jsonl)]
    summary[(summary.json)]
    fit[(activity.fit)]
    png[(chart.png)]

    controller -->|raw SensorSnapshot per tick| rec_integration
    rec_integration --> aggregator
    aggregator -->|completed 1 Hz RecorderSample| recorder
    recorder --> samples
    recorder --> summary
    recorder --> fit_exporter
    fit_exporter --> fit
    rec_integration -->|export_chart_image on commit| workout_screen
    workout_screen --> png
    rec_integration -->|upload executor queue| strava
    rec_integration -->|upload executor queue| icu
    fit --> strava
    fit --> icu
    controller -->|save without a live recording| manual_save
    manual_save --> fit
```

## Workout Authoring Routing (Library / Builder / Blocks)

```mermaid
flowchart TD
    rider((Rider))

    subgraph UI[Authoring UI]
        library_screen[WorkoutLibraryScreen]
        builder_screen[WorkoutBuilderScreen]
        block_dialog[BlockManagerDialog]
        main_window[MainWindow]
        workout_screen[WorkoutScreen]
    end

    subgraph CoreParse[Parse / Export]
        builder_parser[builder_parser]
        mrc[mrc_parser / mrc_exporter]
        zwo[zwo_parser / zwo_exporter]
        erg[erg_parser]
        workout_files[workout_files]
        library[WorkoutLibrary]
    end

    subgraph Store[Storage]
        blocks_store[(blocks.json)]
        user_workouts[(user workouts .mrc/.zwo/.erg)]
    end

    rider --> builder_screen
    rider --> library_screen
    builder_screen -->|parse_builder_text| builder_parser
    builder_screen --> block_dialog
    block_dialog -->|save_blocks| blocks_store
    builder_parser -.expands @block refs.-> blocks_store
    builder_screen -->|save as MRC| mrc
    builder_screen -->|save as ZWO| zwo
    builder_screen -->|workout_saved -> refresh| library_screen
    builder_screen -->|workout_load_requested| main_window
    library --> user_workouts
    library -->|parse by extension| workout_files
    workout_files --> mrc
    workout_files --> zwo
    workout_files --> erg
    library_screen -->|refresh / parse headers| library
    library_screen -->|workout_selected| main_window
    library_screen -->|workout_edit_requested| builder_screen
    workout_screen -->|load_from_library_requested| main_window
    workout_screen -->|load_planned_workout_requested| planned[PlannedWorkoutLoader]
    planned -->|today's intervals.icu workout| main_window
    main_window -->|load_workout| controller[WorkoutSessionController]
    controller --> workout_screen
```

## Course Ride Routing (Course file -> Trainer grade / Chart / Map)

```mermaid
flowchart TD
    rider((Rider))
    files[(course .gpx / .tcx / .fit)]

    subgraph Parse[Course parsing]
        gpx[gpx_parser]
        tcx[tcx_parser]
        fitc[fit_course_parser]
        course_files[course_files: points + POIs]
        course[Course / CoursePoint / CoursePoi]
    end

    subgraph Ride[Ride]
        import_dialog[CourseImportDialog / CourseSplitDialog / CourseLapDialog]
        controller[WorkoutSessionController]
        course_ride[CourseRide]
        physics[bike_physics.advance_speed]
        mode_state[ModeState set_course_grade]
        bridge_mgr[FTMSBridgeManager _apply_simulation]
        trainer[(Smart Trainer FTMS simulation)]
    end

    subgraph View[Display / Export]
        workout_screen[WorkoutScreen]
        chart[WorkoutChart load_course]
        map[CourseMapPanel / CourseMapWidget]
        tiles[NetworkTileProvider + tile cache]
        chart_export[ChartImageExport + map_export]
        png[(ride image .png)]
    end

    rider --> import_dialog
    files --> gpx & tcx & fitc
    gpx & tcx & fitc --> course_files --> course
    import_dialog -->|from/to distance, laps| controller
    course --> controller
    controller -->|each tick: power| course_ride
    course_ride --> physics
    physics -->|virtual speed, distance| course_ride
    course_ride -->|current grade| mode_state
    mode_state --> bridge_mgr --> trainer
    controller -->|load_course_chart / set_course_mode| workout_screen
    workout_screen --> chart
    workout_screen --> map
    map --> tiles
    controller -->|on commit| chart_export --> png
```

## DFA α1 Routing (HR strap -> Tile)

```mermaid
flowchart TD
    hr[(HR Sensor HRS)]
    devices_screen[DevicesScreen hrs decoder]
    main_window[MainWindow]
    controller[WorkoutSessionController _update_dfa]
    pipeline[DfaPipeline ingest_rr / maybe_recompute]
    artifact[artifact: classify_beats / correct_artifacts]
    dfa[dfa.compute_alpha1]
    tile[TileComputation DFA tile]
    workout_screen[WorkoutScreen]

    hr -->|RR intervals in HR measurement| devices_screen
    devices_screen -->|SensorSample with RR| main_window
    main_window -->|receive_rr_intervals_ms, selected HR device only| controller
    controller -->|only while the DFA tile is shown| pipeline
    pipeline --> artifact --> dfa
    dfa -->|DfaRecord every 5 s| pipeline
    pipeline -->|latest_dfa_record| tile --> workout_screen
```

### Diagram Node Key

- `WorkoutHotkeys`: `opencycletrainer/ui/hotkeys.py`
- `WorkoutScreen`: `opencycletrainer/ui/workout_screen.py`
- `DevicesScreen`: `opencycletrainer/ui/devices_screen.py`
- `SettingsScreen`: `opencycletrainer/ui/settings_screen.py`
- `MainWindow`: `opencycletrainer/ui/main_window.py`
- `WorkoutSessionController`: `opencycletrainer/ui/workout_controller.py`
- `ModeState`: `opencycletrainer/ui/mode_state.py`
- `OpenTrueUpState`: `opencycletrainer/ui/opentrueup_state.py`
- `FTMSBridgeManager`: `opencycletrainer/ui/ftms_bridge_manager.py`
- `RecorderIntegration`, `SensorSnapshot`: `opencycletrainer/ui/recorder_integration.py`
- `WorkoutEngine`, `WorkoutEngineSnapshot`: `opencycletrainer/core/workout_engine.py`
- `WorkoutEngineFTMSBridge`, `FTMSControl`: `opencycletrainer/core/control/ftms_control.py`
- `OpenTrueUpController`: `opencycletrainer/core/control/opentrueup.py`
- `HybridModeController`: `opencycletrainer/core/control/hybrid_mode.py` (implemented + tested, not yet wired into the live UI)
- `OneSecondAggregator`: `opencycletrainer/core/one_second_aggregator.py`
- `DeviceManager`: `opencycletrainer/devices/device_manager.py` (abstract; `BleakDeviceBackend`, `MockDeviceBackend` implement it)
- `BleakDeviceBackend`, `BleakFTMSControlTransport`: `opencycletrainer/devices/ble_backend.py`
- `Protocol Decoders`: `opencycletrainer/devices/decoders/*` (ftms, cps, hrs, csc)
- `SensorSample`: `opencycletrainer/core/sensors.py`
- `WorkoutRecorder`, `RecorderSample`: `opencycletrainer/core/recorder.py`
- `FitExporter`: `opencycletrainer/core/fit_exporter.py`
- `Strava Sync Service`: `opencycletrainer/integrations/strava/sync_service.py` (FIT upload only)
- `intervals.icu Sync Service`: `opencycletrainer/integrations/intervalsicu/sync_service.py`; FTP sync in `ftp_service.py` and `ui/ftp_sync.py`; planned workouts in `planned_workouts.py` and `ui/planned_workout_loader.py`
- `gpx_parser` / `tcx_parser` / `fit_course_parser` / `course_files`: `opencycletrainer/core/`
- `Course`, `CoursePoint`, `CoursePoi`: `opencycletrainer/core/course_model.py`
- `CourseRide`: `opencycletrainer/core/course_ride.py`; `bike_physics`: `opencycletrainer/core/bike_physics.py`
- `CourseImportDialog` and friends: `opencycletrainer/ui/course_import_dialog.py`
- `CourseMapPanel` / `CourseMapWidget`: `opencycletrainer/ui/course_map.py`; tiles in `opencycletrainer/ui/map_tiles.py`
- `ChartImageExport`: `opencycletrainer/ui/chart_export.py`; map drawing in `opencycletrainer/ui/map_export.py`
- `DfaPipeline`: `opencycletrainer/core/dfa/pipeline.py`; maths in `core/dfa/dfa.py`, artifact correction in `core/dfa/artifact.py`
- `PlannedWorkoutLoader`: `opencycletrainer/ui/planned_workout_loader.py`
- `WorkoutLibraryScreen`: `opencycletrainer/ui/workout_library_screen.py`
- `WorkoutBuilderScreen`: `opencycletrainer/ui/workout_builder_screen.py`
- `BlockManagerDialog`: `opencycletrainer/ui/block_manager_dialog.py`
- `WorkoutLibrary`: `opencycletrainer/core/workout_library.py`
- `builder_parser`: `opencycletrainer/core/builder_parser.py`
- `mrc_parser` / `mrc_exporter`: `opencycletrainer/core/mrc_parser.py`, `opencycletrainer/core/mrc_exporter.py`
- `zwo_parser` / `zwo_exporter`: `opencycletrainer/core/zwo_parser.py`, `opencycletrainer/core/zwo_exporter.py`
- `erg_parser`: `opencycletrainer/core/erg_parser.py`
- `workout_files`: `opencycletrainer/core/workout_files.py`
- `blocks` store: `opencycletrainer/storage/blocks.py`
- Supporting pieces not drawn: settings (`storage/settings.py`, `ui/settings_screen.py`), credentials (`integrations/keyring_support.py` with a file fallback in `integrations/intervalsicu/key_store.py`; `integrations/strava/token_store.py`), spin-down (`core/control/spin_down.py`, `ui/spin_down_dialog.py`), capabilities dialogs (`ui/*_capabilities_dialog.py`), paired-device autoconnect (`storage/paired_devices.py`, `DevicesScreen.start_autoconnect`), OpenTrueUp offsets (`storage/opentrueup_offsets.py`), toasts (`ui/toast.py`)

## Notes

- `WorkoutSessionController` is the central integration point. Trainer control and live
  recording go through dedicated collaborators: `FTMSBridgeManager`, `RecorderIntegration`,
  `ModeState`, `OpenTrueUpState`, `PauseState`, `ChartHistory`, `TileComputation`,
  `PowerHistory`, and `TrainerConnection`. It also owns `DfaPipeline`, `ExternalEnergyTracker`,
  `CadenceHistory`, `PedalingDetector` and `IntervalStats`, plus a `WorkoutRecorder` and
  `FitExporter` of its own for saving a ride manually.
- `FTMSBridgeManager` owns the `WorkoutEngineFTMSBridge` and a single-worker
  `ThreadPoolExecutor`, so all blocking BLE control-point writes (with their indication
  acks) run off the Qt UI thread. Snapshots, power samples, and jog/mode actions are
  submitted as queued executor tasks.
- `RecorderIntegration` feeds raw per-tick sensor snapshots through a `OneSecondAggregator`,
  so the recorder only ever receives deterministic 1 Hz bins regardless of tick jitter. It
  also owns kJ accumulation and two background executors: one for saving and one queueing
  FIT uploads to Strava and intervals.icu.
- Cadence source selection uses priority: dedicated cadence sensor > power meter > trainer.
  Power metrics prefer the bike power meter (CPS), falling back to trainer (FTMS) power.
- OpenTrueUp receives both trainer and bike power samples through the bridge, computes an
  offset, and can trigger an ERG target re-application on the trainer.
- The workout authoring subsystem (Library + Builder + reusable Blocks) parses and exports
  MRC and ZWO files, and also reads ERG files (targets in watts, scaled to the rider's FTP
  when the file states the FTP it was written for). `workout_files` picks the parser by
  file extension for the library, the builder and the workout tab. The builder's `@name` block references are expanded by `builder_parser`
  from `blocks.json` at the current FTP; block bodies cannot themselves reference blocks
  (single-level nesting only).
- On a course ride, `CourseRide` turns rider power into virtual speed with `bike_physics`
  and feeds the current grade to `ModeState`, which the bridge sends as an FTMS simulation
  command. The map is drawn from cached tiles and also composed into the saved ride image.
- DFA α1 is computed only while its tile is shown, from RR intervals of the selected HR
  device, recomputed every 5 seconds after artifact correction.
- `HybridModeController` (`core/control/hybrid_mode.py`) is still not wired into the live UI;
  Hybrid mode runs its own logic in `ui/mode_state.py`.

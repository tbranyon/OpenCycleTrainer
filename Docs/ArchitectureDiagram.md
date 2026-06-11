# OpenCycleTrainer Architecture Diagram

This diagram documents how control commands, live telemetry, recording, and workout
authoring route through the project modules.

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
        main_window[MainWindow on_sensor_sample]
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
    main_window -->|receive_power / bike_power / hr / cadence / speed / pedal_balance / energy_kj| controller
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
    rec_integration -->|auto-sync upload queue| strava
    fit --> strava
    png -->|optional image upload| strava
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
        library[WorkoutLibrary]
    end

    subgraph Store[Storage]
        blocks_store[(blocks.json)]
        user_workouts[(user workouts .mrc/.zwo)]
    end

    rider --> builder_screen
    rider --> library_screen
    builder_screen -->|parse_builder_text| builder_parser
    builder_screen --> block_dialog
    block_dialog -->|save_blocks| blocks_store
    builder_parser -.expands @block refs.-> blocks_store
    builder_screen -->|save as MRC| mrc
    builder_screen -->|save as ZWO| zwo
    builder_screen -->|workout_saved| library
    library --> user_workouts
    library_screen -->|refresh / parse headers| library
    library_screen -->|workout_selected| main_window
    library_screen -->|workout_edit_requested| builder_screen
    workout_screen -->|load_from_library_requested| main_window
    main_window -->|load_workout| controller[WorkoutSessionController]
    controller --> workout_screen
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
- `DeviceManager`: `opencycletrainer/devices/device_manager.py` (abstract; `BleakDeviceBackend`, `MockBackend` implement it)
- `BleakDeviceBackend`, `BleakFTMSControlTransport`: `opencycletrainer/devices/ble_backend.py`
- `Protocol Decoders`: `opencycletrainer/devices/decoders/*` (ftms, cps, hrs, csc)
- `SensorSample`: `opencycletrainer/core/sensors.py`
- `WorkoutRecorder`, `RecorderSample`: `opencycletrainer/core/recorder.py`
- `FitExporter`: `opencycletrainer/core/fit_exporter.py`
- `Strava Sync Service`: `opencycletrainer/integrations/strava/sync_service.py`
- `WorkoutLibraryScreen`: `opencycletrainer/ui/workout_library_screen.py`
- `WorkoutBuilderScreen`: `opencycletrainer/ui/workout_builder_screen.py`
- `BlockManagerDialog`: `opencycletrainer/ui/block_manager_dialog.py`
- `WorkoutLibrary`: `opencycletrainer/core/workout_library.py`
- `builder_parser`: `opencycletrainer/core/builder_parser.py`
- `mrc_parser` / `mrc_exporter`: `opencycletrainer/core/mrc_parser.py`, `opencycletrainer/core/mrc_exporter.py`
- `zwo_parser` / `zwo_exporter`: `opencycletrainer/core/zwo_parser.py`, `opencycletrainer/core/zwo_exporter.py`
- `blocks` store: `opencycletrainer/storage/blocks.py`

## Notes

- `WorkoutSessionController` is the central integration point. It no longer talks to the
  trainer, recorder, or OpenTrueUp directly; instead it composes dedicated collaborators:
  `FTMSBridgeManager`, `RecorderIntegration`, `ModeState`, `OpenTrueUpState`, `PauseState`,
  `ChartHistory`, `TileComputation`, `PowerHistory`, and `TrainerConnection`.
- `FTMSBridgeManager` owns the `WorkoutEngineFTMSBridge` and a single-worker
  `ThreadPoolExecutor`, so all blocking BLE control-point writes (with their indication
  acks) run off the Qt UI thread. Snapshots, power samples, and jog/mode actions are
  submitted as queued executor tasks.
- `RecorderIntegration` feeds raw per-tick sensor snapshots through a `OneSecondAggregator`,
  so the recorder only ever receives deterministic 1 Hz bins regardless of tick jitter. It
  also owns kJ accumulation and the background Strava upload queue (a second executor).
- Cadence source selection uses priority: dedicated cadence sensor > power meter > trainer.
  Power metrics prefer the bike power meter (CPS), falling back to trainer (FTMS) power.
- OpenTrueUp receives both trainer and bike power samples through the bridge, computes an
  offset, and can trigger an ERG target re-application on the trainer.
- The workout authoring subsystem (Library + Builder + reusable Blocks) parses and exports
  MRC and ZWO files. The builder's `@name` block references are expanded by `builder_parser`
  from `blocks.json` at the current FTP; block bodies cannot themselves reference blocks
  (single-level nesting only).
- Current implementation gap: resistance setpoints are sent to the trainer during a workout
  (via the bridge's `on_engine_snapshot` with `manual_resistance_level`), but a manual
  resistance *jog* still only updates internal/UI state and does not immediately push a
  resistance command (marked TODO in `ui/workout_controller.py`).

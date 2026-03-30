# OpenCycleTrainer Architecture Diagram

This diagram documents how control commands and live data currently route through the project modules.

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

    subgraph Runtime[Workout Runtime]
        controller[WorkoutSessionController]
        engine[WorkoutEngine]
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
    workout_screen -->|control actions| controller
    controller -->|engine commands| engine
    engine -->|snapshots| controller
    devices_screen -->|trainer_device_changed| main_window
    main_window -->|set_trainer_control_target| controller
    controller -->|snapshot mode jog| bridge
    controller -->|power samples| bridge
    bridge -->|offset adjust| opentrueup
    bridge -->|target power resistance| ftms_control
    ftms_control --> ftms_transport
    ftms_transport --> ble_backend
    ble_backend -->|gatt write ack| trainer
```

## Telemetry Routing (Devices -> UI)

```mermaid
flowchart TD
    subgraph Sources[Device Sources]
        trainer[(Trainer)]
        pm[(Power Meter)]
        hr[(HR Sensor)]
        csc[(Cadence/Speed Sensor)]
    end

    subgraph BLEStack[BLE + Decode]
        ble_backend[BleakDeviceBackend]
        devices_screen[DevicesScreen]
        decoders[Protocol Decoders]
        sensor_sample[SensorSample]
    end

    subgraph App[Application]
        main_window[MainWindow on_sensor_sample]
        controller[WorkoutSessionController receive_*]
        workout_screen[WorkoutScreen tiles charts]
    end

    trainer --> ble_backend
    pm --> ble_backend
    hr --> ble_backend
    csc --> ble_backend
    ble_backend -->|BLE notifications| devices_screen
    devices_screen --> decoders
    decoders --> sensor_sample
    sensor_sample -->|signal: sensor_sample_received| main_window
    main_window -->|receive_power/hr/cadence/speed| controller
    controller -->|live metrics/charts/offset| workout_screen
```

## Recording/Export Routing (Controller -> Storage/Cloud)

```mermaid
flowchart TD
    controller[WorkoutSessionController]
    recorder[WorkoutRecorder]
    fit_exporter[FitExporter]
    workout_screen[WorkoutScreen]
    strava[Strava Sync Service]

    samples[(samples.jsonl)]
    summary[(summary.json)]
    fit[(activity.fit)]
    png[(chart.png)]

    controller -->|1 Hz RecorderSample| recorder
    recorder --> samples
    recorder --> summary
    recorder --> fit_exporter
    fit_exporter --> fit
    controller -->|optional chart export trigger| workout_screen
    workout_screen --> png
    fit -->|auto-sync optional| strava
    png -->|optional image upload| strava
```

### Diagram Node Key

- `WorkoutHotkeys`: `opencycletrainer/ui/hotkeys.py`
- `WorkoutScreen`: `opencycletrainer/ui/workout_screen.py`
- `DevicesScreen`: `opencycletrainer/ui/devices_screen.py`
- `MainWindow`: `opencycletrainer/ui/main_window.py`
- `WorkoutSessionController`: `opencycletrainer/ui/workout_controller.py`
- `WorkoutEngine`: `opencycletrainer/core/workout_engine.py`
- `WorkoutEngineFTMSBridge`, `FTMSControl`: `opencycletrainer/core/control/ftms_control.py`
- `OpenTrueUpController`: `opencycletrainer/core/control/opentrueup.py`
- `BleakDeviceBackend`, `BleakFTMSControlTransport`: `opencycletrainer/devices/ble_backend.py`
- `Protocol Decoders`: `opencycletrainer/devices/decoders/*`
- `SensorSample`: `opencycletrainer/core/sensors.py`
- `WorkoutRecorder`: `opencycletrainer/core/recorder.py`
- `FitExporter`: `opencycletrainer/core/fit_exporter.py`
- `Strava Sync Service`: `opencycletrainer/integrations/strava/sync_service.py`

## Notes

- `WorkoutSessionController` is the central integration point between UI commands, engine snapshots, trainer control, and recording.
- Cadence source selection in the controller uses priority: dedicated cadence sensor > power meter > trainer.
- OpenTrueUp receives both trainer and bike power samples, computes an offset, and can trigger ERG target re-application.
- Current implementation gap: resistance jog updates internal/UI resistance state, but does not yet send a resistance command to the trainer (marked TODO in `ui/workout_controller.py`).

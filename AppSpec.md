# OpenCycleTrainer
## Software Requirements Specification *(Draft v0.1)*

---

## 1. Overview

### 1.1 Purpose

OpenCycleTrainer is an open-source desktop application for controlling indoor smart trainers (via BLE FTMS), executing structured workouts, and recording/exporting activity data in FIT format for manual upload to third-party platforms.

The application is designed to provide:

- Structured workout execution
- Free ride mode (no default power target) 
- kJ-based workouts (in addition to the traditional time-based)
- ERG and resistance mode control
- OpenTrueUp (match ERG targets to on-bike PM)
- Local data storage with no required network connection

### 1.2 License

OpenCycleTrainer will be released under the **Apache License 2.0**.

### 1.3 Supported Platforms

**Initial targets:**
- Windows 10/11 (MSI installer)
- Linux (Flatpak)

**Future:**
- macOS (optional)

### 1.4 Technology Stack

| Component | Technology |
|---|---|
| Language | Python |
| UI Framework | PySide6 (Qt for Python, LGPL) |
| FIT Export Library | fit-tool (BSD-3-Clause licensed) |
| BLE Communication | bleak |

---

## 2. System Architecture (High-Level)

The application shall be modular and structured to allow future expansion.

### 2.1 Core Modules

1. **Device Manager**
   - BLE scanning and pairing
   - Device abstraction layer
   - Power source selection
   - Calibration commands

2. **Workout Engine**
   - Internal workout state machine
   - Interval scheduling
   - kJ integration
   - Lead-time handling

3. **Control Layer**
   - ERG mode control
   - Resistance mode control
   - OpenTrueUp module (offset-based)

4. **Recorder**
   - 1 Hz activity logging
   - Local file persistence
   - FIT export

5. **UI Layer**
   - Workout screen
   - Device screen
   - Settings screen

### 2.2 Future-Proofing Modules

Headings reserved for later expansion:

- ANT+ Support *(Deferred)*
- RR Interval & DFA1alpha Module *(Deferred)*
- API Upload Module (Strava, intervals.icu, Garmin)
- Custom `.oct` Exporter
- Localization Framework

---

## 3. Device Support

### 3.1 Supported Protocols (BLE GATT)

Must support:

- **FTMS** (Fitness Machine Service) – Trainer control
- **CPS** (Cycling Power Service) – Power meters
- **HRS** (Heart Rate Service)
- **CSC** (Cycling Speed and Cadence)

> ANT+ is deferred but architecture shall allow later addition.

### 3.2 Power Source Selection Logic

Primary power source selection shall follow:

1. User-selected source (explicit override)
2. Dedicated bike-based power meter (preferred over trainer)
3. Trainer power (fallback)

Selection shall persist locally per device pairing.

### 3.3 Device Screen Requirements

The Devices screen shall allow:

- BLE scan and pairing
- Devices found should be filtered to only relevant devices (power meters, trainers, HRMs, cadence sensors). Do not display irrelevant devices.
- Display of:
  - Device name
  - Connection status
  - Battery level (if available)
- Selection of primary power source
- Sending zero-offset command to strain gauge power meters
- No trainer spindown support (v1), may be added in future versions
- Clear indication of paired devices vs available unpaired devices
- Clear indication of type of device (PM, HRM, Trainer, etc.)

### 3.4 Calibration

- Only zero-offset calibration supported.
- Button labeled **"Calibrate"** in UI.
- Available only for strain-gauge PMs.
- No spindown calibration for trainers in v1.

---

## 4. Workout System

### 4.1 Import Format (v1)

Support **MRC files** using:
- `MINUTES`
- `PERCENT`

Support:
- Step intervals
- Linear ramps

> No text cue support (v1)

**Future:** ZWO, ERG, FIT workout import *(deferred)*

### 4.2 Internal Workout Format

Internal canonical schema: **`.octw`**

> Essentially MRC extended to include kJ targets instead of time, for now (more may be added in the future)

In the kJ target case, instead of MINUTES in the first column, the first column would contain "kJ", and the interval would persist until that many kJ of work are completed in that interval. The PERCENT field could be set to 0 for free ride (no default ERG target).  
Otherwise, an .octw looks like a .MRC.

### 4.3 Workout Execution

#### 4.3.1 Modes

- Workout Mode
- kJ-based Mode
- Free Ride Mode

#### 4.3.2 kJ-Based Completion

kJ shall be computed as:

```
kJ = ∫ Power (Watts) over time
```

In kJ mode:
- Steps are completed based on kJ work completed rather than time elapsed

### 4.4 Lead Time

- Applies to step transitions only.
- Trainer command sent X seconds before interval boundary.
- Ramps are not modified.
- Persist this setting through local nonvolatile storage
- Applies to all control modes.
- Does not apply to kJ based workouts.

### 4.5 Pause / Resume Behavior

**On Pause:**
- ERG setpoint = 0 W or Resistance setpoint = 0% (depending on current control mode)
- Recording paused

**On Resume:**
- 3-second ramp-in to target
- Recording resumes after ramp completes
- Show a message to the user indicating the ramp-in is active and a countdown
- User can still initiate a brand new pause during the ramp in, restarting the pause/resume logic

---

## 5. Control System

### 5.1 ERG Mode

- Send target power via FTMS
- ERG setpoint = 0 W on pause/finish

### 5.2 Resistance Mode

- Support switching between ERG and resistance mode
- User may manually enter target power in Free Ride mode

### 5.3 Hybrid Mode

- Use ERG mode in recovery intervals (anything less than 56% FTP)
- Use resistance mode in work intervals (anything >=56% FTP), and remember the last set resistance throughout a workout
- Control switches seamlessly when a new interval starts

---

## 6. OpenTrueUp (Offset-Based Correction)

OpenTrueUp is an offset-based correction system using a bike PM as truth power.

### 6.1 Algorithm

- 30-second moving average window
- Update trainer offset every 5 seconds (don't send new command if offset is unchanged)
- `Offset = (Bike PM avg – Trainer power avg)`
- Offset applied to ERG target

> Trainer commands are not continuously adjusted; only periodic offset adjustments applied.

### 6.2 Persistence

Offsets shall be stored locally:
- Keyed by trainer + PM device pair
- Reused on subsequent sessions

### 6.3 Dropout Behavior

If bike PM missing > 3 seconds:
- Hold trainer setpoint
- Temporarily use trainer power (with last good offset applied)
- Resume offset calculation when PM returns

### 6.4 User Visibility

The 30-second offset value shall be exposed in UI for informational purposes when enabled by the user.

### 6.5 Resistance Mode

When in Resistance Mode, OpenTrueUp has no effect, since Resistance is effectively open loop. However, the trainer vs. bike PM offset should still be calculated in the background during this time if OpenTrueUp is enabled.

---

## 7. Recording & Data Export

### 7.1 Logging Rate

- **1 Hz** recording
- Timestamped samples

**Data fields recorded:**

| Field | Notes |
|---|---|
| Timestamp | UTC |
| Target power | |
| Trainer power | |
| Bike PM power | |
| HR | |
| Cadence | |
| Speed | If available |
| Mode | |
| ERG setpoint | |
| Total kJ | |

### 7.2 File Export

- **Format:** FIT
- **Library:** fit-tool
- No API upload in v1.

### 7.3 Local Storage

Activities stored locally:
- FIT file
- JSON summary

**Filename format:**
```
[WorkoutName]_[YYYYMMDD]_[HHMM].[EXT]
```

**Example:**
```
Threshold_20260309_1842.fit
```

### 7.4 Time & Units

- **Units:** Watts, kJ, bpm
- **Date format:** dd/mm/yyyy (display)
- **Time format:** 24-hour hh:mm:ss.x
- FIT timestamps stored in UTC

### 7.5 Future Export Format

Future work may involve export of CSVs or specially-defined format for analyzing data not covered by FIT format. No scaffolding is needed at this time, only keep the code structured in a way that doesn't inhibit this in the future.

---

## 8. UI Requirements

### 8.1 General UI Behavior

- UI shall update key ride metrics (power, cadence, HR, speed, elapsed time, total kJ) in near real-time.
- Main workout controls (Start, Pause, Resume, End) shall be accessible on the primary workout screen.
- User-facing labels shall use clear cycling terminology consistent with this specification.
- Critical trainer/device errors shall be shown as visible in-app alerts.
- Use icons for functions where sensible and clear. Do not overuse icons.

### 8.2 Workout Screen Requirements

- Display workout name as a title at the top center
- Display mandatory and configurable data fields
- Display current mode state (ERG/Resistance/Hybrid).
- Display live plot of 1s average power, power target, and heart rate vs. time, for the current interval
- Live plot as above but for the entire workout.
- Each trace should use contrasting colors

#### 8.2.1 Mandatory Workout Data Fields
The following data fields should be displayed at all times in the workout.
* Time elapsed
* Time remaining or kJ remaining (for kJ-target rides)
* Interval time/work remaining

#### 8.2.2 Configurable Workout Data Fields
The user shall be allowed to select up to 8 "tiles" to be displayed live during workouts in addition to the mandatory fields, from the following options:
* Windowed average power (window configured in settings, 1-10s)
* Windowed average %FTP
* Interval average power
* Workout average power
* Workout normalized power
* Heart Rate
* Workout Average HR
* Interval Average HR
* kJ work completed
* kJ work completed (current interval)

#### 8.2.3 Data Field Appearance
The fields should be displayed as tiles which are resized accordingly based on the user's selections and when the window is resized. The configurable tiles should occupy no more than 2 rows on the UI at any time. The mandatory fields should be displayed prominently in a top row above the configurable fields, with interval time/work in the center and slightly larger than the other two. Total time elapsed should be to the left of interval time/work.

### 8.3 Devices Screen Requirements

- Present paired devices separately from unpaired discovered devices.
- Show device type, connection status, and battery level (if available).
- Provide actions for pair, unpair, connect, disconnect, and calibrate (when supported).

### 8.4 Settings Screen Requirements

- Allow configuration of FTP, lead time, display units, and default workout behavior.
- Allow enabling/disabling optional features that do not affect safety-critical control behavior
- Allow enabling/disabling of OpenTrueUp
- Allow configuration of visible fields during workouts
- Persist user settings locally between sessions.

### 8.5 Hotkeys
|Key|Function|
|---|--------|
|T|Toggle ERG/Resistance/Hybrid control|
|1|Add 1 minute to interval (or 10kJ in kJ mode)|
|5|Add 5 minutes to interval (or 50kJ in kJ mode)|
|Tab|Skip remainder of current interval|
|Up/Down Arrows|Jog %FTP target/resistance level by 1%|
|Left/Right Arrows|Jog %FTP target/resistance level by 5%|
|Spacebar|Pause/Resume|

### 8.6 Workout Completion
When a workout finishes, the user should be presented with a workout summary screen. This screen should show "Great job!" in title/Heading 1 type text (large, prominent) with a workout summary below. The summary should include workout time, kJ burned, average and normalized power, TSS, and average heart rate.

---

## 9. Performance Requirements

| Metric | Target |
|---|---|
| Sensor update rate | 1–4 Hz (via BLE notifications) |
| UI metrics refresh | 1–4 Hz |
| Charts | 30–60 FPS |
| OpenTrueUp update cadence | Every 5 s |
| Command latency | < 150 ms average |
| Logging | Must not block control loop |

---

## 10. Privacy & Security

- No network connection required to run
- No telemetry by default
- All data collection strictly opt-in
- API keys (future) stored encrypted locally

---

## 11. Packaging & Distribution

- Windows MSI installer
- Linux Flatpak
- No nightly builds required
- CI for Windows and Linux builds

---

## 12. Testing

### 12.1 Unit Tests

- Workout engine
- OpenTrueUp module
- Device abstraction
- FIT export

### 12.2 Integration Tests

- Simulated trainer + PM
- Offset persistence
- Dropout handling
- Lead-time behavior

---

## 13. Localization

- Default language: US English
- Architecture shall not preclude future language additions

---

## 14. Storage & Configuration

- User FTP stored locally
- Device pairing and offset data stored locally
- Windows: use %APPDATA%\OpenCycleTrainer\ 
- Linux: use ~/.config/opencycletrainer/ for config storage, ~/.local/share/opencycletrainer/ for exported/generated data

---

## 15. Deferred Features (Future Phases)

- ANT+ support
- Strava/Garmin/intervals.icu API sync
- RR interval capture
- DFA1alpha analysis
- LT1 ramp test mode
- Trainer spindown calibration
- ZWO/ERG/FIT workout import
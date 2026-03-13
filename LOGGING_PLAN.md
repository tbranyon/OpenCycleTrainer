# Logging Improvement Plan

## Current State
- Logging infrastructure exists (`logging_config.py`) with console + file handlers.
- Only one active logger (`recorder.py`) with one log call (FIT export failure).
- FTMS errors surface to UI via Qt signals but are never written to the log file.
- Many `except` blocks silently swallow errors with `pass` or silent returns.

---

## Planned Changes (Priority Order)

### 1. FTMS Control Errors — `ftms_control.py` / `workout_controller.py`
**Value: High.** These are the most actionable trainer errors. They already reach the UI, but nothing is persisted for debugging.

- Add a logger to `ftms_control.py`.
- Log `WARNING` when `FTMSControlAckTimeoutError` is raised (include command context).
- Log `ERROR` when `FTMSControlAckError` is raised (include result code).
- In `workout_controller.py`, log `ERROR` in the `_report_error` callback before emitting the UI signal.

### 2. FIT File Write Success — `recorder.py` / `fit_exporter.py`
**Value: High.** Users need confirmation that their workout was saved. Easy to add, high visibility.

- After successful `export_activity()`, log `INFO` with the output file path and file size in KB.
- Add a logger to `fit_exporter.py` for this.

### 3. BLE Backend Silent Failures — `ble_backend.py`
**Value: High.** Silent `except: pass` blocks hide connection/notification errors that are very hard to debug otherwise.

- Add a logger to `ble_backend.py`.
- Replace `pass` in the following with `logger.warning(...)`:
  - Device connection failure (line ~192)
  - Notify unsubscribe failure (line ~230)
  - CPS control point failure (line ~267)
  - Notify stop failure (line ~296)
  - Device disconnect failure (line ~319)
- Shutdown `pass` (line ~136) can stay silent — it is expected noise during teardown.
- BLE timeout returning `None` (~280) can stay silent — expected behavior.

### 4. Recorder / WorkoutController Silent Returns — `workout_controller.py`
**Value: Medium.** Silently returning on `RuntimeError` from the recorder means sample loss goes unnoticed.

- Log `WARNING` in each `except RuntimeError: return` block (~lines 402, 428, 517) with a message identifying which operation failed.

### 5. OpenTrueUp Offset Store Parse Failure — `opentrueup_offsets.py`
**Value: Low-Medium.** Silent `pass` on JSON parse failure means corrupt offset data is invisible.

- Add a logger and log `WARNING` when `(TypeError, ValueError)` is caught during offset parsing.

### 6. FIT Exporter Field-Setting Failures — `fit_exporter.py`
**Value: Low.** `(AttributeError, TypeError): continue` silently drops sample fields.

- Log `DEBUG` when a field cannot be set on a `RecordMessage`, including field name and sample value.

### 7. Out-of-Range Sensor Values — `decoders/ftms.py`, `decoders/cps.py`, `decoders/csc.py`
**Value: Medium.** Implausible sensor readings indicate hardware/firmware issues or BLE data corruption. Currently, cadence > 300 RPM is silently dropped with no record.

Ranges to enforce and log `WARNING` when exceeded:

| Field | Source | Range | Notes |
|-------|--------|-------|-------|
| `cadence_rpm` | all three decoders | 0–300 RPM | `_MAX_CADENCE_RPM` guard already exists; just add logging before returning `None` |
| `power_watts` | FTMS, CPS | 0–3000 W | No existing guard; add a check and log but still return the value (sensor may be quirky) |
| `speed_mps` | FTMS, CSC | 0–33.3 m/s (120 km/h) | No existing guard; add check and log |
| `heart_rate_bpm` | FTMS | 0–250 BPM | No existing guard; add check and log |

- For cadence: log at the existing `_MAX_CADENCE_RPM` guard site, no behavioral change.
- For other fields: log `WARNING` with the raw value but do **not** suppress the value — the caller can decide what to do with it.
- Add a logger to each decoder module.

---

## Out of Scope
- `devices_screen.py` scan failure already surfaces to UI — add logging only if it proves noisy in practice.
- No new alert banners; logging to file/console is sufficient for all items above unless noted.
- No changes to logging infrastructure or log levels.

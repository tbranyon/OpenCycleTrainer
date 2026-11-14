# Recommendations

Based on a read-through of `main` at `89b3ead` (v0.5.1). Nothing here was profiled or
run, so performance magnitudes are estimates. Items already in `TODOs.md` are left out.
Each list is ordered by value for effort.

## 1. Performance

No measured bottleneck is caused by Python itself: the load is a few sensors at 1–4 Hz.
The problems are work repeated on the UI thread.

1. **DFA α1 recomputes on the UI thread even when its tile is hidden**, using per-beat
   Python loops (`core/dfa/artifact.py:83-108`). Vectorize the rolling median and
   quantile, then move the recompute to a worker.
2. **Finishing a ride encodes the FIT file on the UI thread and computes metrics twice**
   (`core/recorder.py:222-270`). Reuse the summary metrics and export on the executor
   Strava upload already uses.
3. **Startup probes the OS keyring three times, uncached** (`ui/main_window.py:61-68`).
   Probe once per process.
4. **`matplotlib` is declared and bundled but never imported.** Removing it from
   `pyproject.toml` and the Flatpak manifest shrinks every installer.

**Bigger bet:** add a headless benchmark that replays a simulated three-hour ride
through the mock backend and times each tick. It makes item 1 measurable and guards
against regressions. A rewrite in Rust or C++ would not fix any item above; it would
only help install size and startup time.

## 2. Functionality

1. **Resistance jog is delayed in structured workouts.** During a steady interval the
   new level is not sent until the next interval change, ramp tick or resume; free ride
   sends it at once (`ui/workout_controller.py:574`,
   `core/control/ftms_control.py:454-465`).
2. **Crash recovery.** Samples are already streamed to `*.samples.jsonl` during the
   ride, but nothing looks for orphaned files at startup. Offer to finalize them into a
   FIT file.
3. **ERG stall protection.** There is no "spiral of death" handling: when cadence
   collapses under ERG, ease the target and ramp back in.
4. **Record distance and left/right balance in the FIT file.** Balance is decoded
   (`core/sensors.py:46`) and then dropped; distance can be integrated from speed.
5. **Pull today's planned workout from intervals.icu.** Authentication already exists,
   and this removes the manual file shuffle for anyone following a plan.
6. **FTP ramp test** that proposes a new FTP. FTP is manual only today, and it drives
   every percentage-based workout.
7. **Finish or remove half-built pieces:** `display_units` is stored but never read,
   and `core/control/hybrid_mode.py` is unused; the live Hybrid mode runs a separate
   copy of that logic in `ui/mode_state.py`.
8. **Import `.erg` workouts** (close to the existing MRC parser), plus favourites and a
   ride-history browser.

**Bigger bets**

- **Closed-loop α1 control.** The app already computes DFA α1 live. Let ERG hold the
  rider at a chosen α1 (0.75 is the usual aerobic-threshold marker) with slow, bounded
  adjustments.
- **Slope and simulation mode** via FTMS Indoor Bike Simulation, optionally following a
  GPX route. The feature flag is already decoded (`devices/decoders/ftms.py:187`), but
  intervals need a grade field and a new control path.
- **Run the core as a local service** (BLE, engine, recorder) with the UI as a client.
  A UI crash would no longer end the ride, and a phone could act as a remote or second
  screen.

## 3. UI/UX

1. **Discard deletes the ride with no confirmation**, and Esc does the same through
   Qt's default dialog behaviour (`ui/workout_summary_dialog.py:272`,
   `ui/workout_controller.py:750`). Confirm first; make Esc harmless.
2. **Stop and skip act instantly, and Tab is the skip key.** One stray keypress skips an
   interval, Tab can no longer move focus, and the hotkeys are not listed anywhere in
   the app (`ui/hotkeys.py:41`). Rebind skip, confirm Stop, add a "?" overlay.
3. **"Load from File" rejects ZWO**, although the Library accepts it
   (`ui/workout_controller.py:315,327`). Loading from the Library is double-click only;
   add a Load button.
4. **First run gives no guidance.** Start is visible with nothing loaded and silently
   does nothing, FTP defaults to 250, and nothing points to Devices. Add a short
   checklist: pair a trainer, set FTP, pick a workout.
5. **Error banners vanish after 5 s** and dismiss by mouse click only
   (`ui/workout_screen.py:642-656`). Keep errors until dismissed.
6. **Devices tab feedback is thin:** no scan progress, no empty state, raw device IDs
   in messages, and Unpair is unconfirmed.
7. **Hard to read from the bike.** Tile values are only 1–4 pt above default, there is
   no fullscreen mode, and the charts have no zone shading or legend.
8. **Dark mode is partial.** Banners, builder hints and the summary dialog hard-code
   colours, although `ui/theme.py` already has a theme-aware palette.
9. **Window size is fixed at 1024×720 and not remembered**, and the summary dialog's
   760×760 minimum is taller than the main window.
10. **After a ride, the banner shows only the file name.** Show the folder and add an
    "Open folder" action.

**Bigger bet: the UI framework**

`core/`, `devices/`, `storage/` and `integrations/` (about 8,600 lines) import no Qt,
so a UI swap touches only `ui/` and `app.py` (about 8,300 lines).

| Option | Gains | Costs |
|---|---|---|
| Stay on PySide6 widgets | Nothing to migrate; items 1–10 are each small | Scaling, theming and big-number layouts stay manual |
| Qt Quick (QML) for the ride screen | GPU-drawn, fluid scaling, same Python core and BLE | Two UI styles in one app during the transition |
| Local web UI over the service split above | Any phone, tablet or TV becomes the display | Browser latency for live charts; packaging a server |
| Flutter or Tauri rewrite | Native mobile apps | Rewrites the BLE layer and FIT export; loses 20k lines of tests |

Recommendation: stay on PySide6 for now and keep Python. Do the service split when a
second screen or phone remote becomes a goal; it makes the UI replaceable without
committing to a framework today.

Open question: `claude/nicegui-refactor-phase-ybn2f` holds a finished eight-phase
NiceGUI port from March that was never merged. Why it was dropped decides whether the
web option above is worth trying again.

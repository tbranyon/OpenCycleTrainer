# Recommendations

Based on a read-through of `main` at `89b3ead` (v0.5.1). Nothing here was profiled or
run, so performance magnitudes are estimates. Items already in `TODOs.md` are left out.
Each list is ordered by value for effort.

## 1. Performance

All of the performance items from the original review are done. No bottleneck found was
caused by Python itself; each was work repeated on, or blocking, the UI thread.

**Bigger bet:** add a headless benchmark that replays a simulated three-hour ride
through the mock backend and times each tick, so per-tick costs that grow with ride
length (like the ones already fixed) are caught before release. A rewrite in Rust or
C++ would not have fixed any of them; it would only help install size and startup time.

## 2. Functionality

1. **Crash recovery.** Samples are already streamed to `*.samples.jsonl` during the
   ride, but nothing looks for orphaned files at startup. Offer to finalize them into a
   FIT file.
2. **ERG stall protection.** There is no "spiral of death" handling: when cadence
   collapses under ERG, ease the target and ramp back in.
3. **Record distance and left/right balance in the FIT file.** Balance is decoded
   (`core/sensors.py:46`) and then dropped; distance can be integrated from speed.
4. **Pull today's planned workout from intervals.icu.** Authentication already exists,
   and this removes the manual file shuffle for anyone following a plan.
5. **FTP ramp test** that proposes a new FTP. FTP is manual only today, and it drives
   every percentage-based workout.
6. **Finish or remove half-built pieces:** `core/control/hybrid_mode.py` is unused;
   the live Hybrid mode runs a separate copy of that logic in `ui/mode_state.py`.
7. **Import `.erg` workouts** (close to the existing MRC parser), plus favourites and a
   ride-history browser.

**Bigger bets**

- **Closed-loop α1 control.** The app already computes DFA α1 live. Let ERG hold the
  rider at a chosen α1 (0.75 is the usual aerobic-threshold marker) with slow, bounded
  adjustments.
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
3. **Loading from the Library is double-click only.** Add a Load button.
4. **First run gives no guidance.** Start is visible with nothing loaded and silently
   does nothing, FTP defaults to 250, and nothing points to Devices. Add a short
   checklist: pair a trainer, set FTP, pick a workout.
5. **Error banners vanish after 5 s** and dismiss by mouse click only
   (`ui/workout_screen.py:642-656`). Keep errors until dismissed.
6. **Hard to read from the bike.** Tile values are only 1–4 pt above default, there is
   no fullscreen mode, and the charts have no zone shading or legend.
7. **Dark mode is partial.** Banners, builder hints and the summary dialog hard-code
   colours, although `ui/theme.py` already has a theme-aware palette.
8. **Window size is fixed at 1024×720 and not remembered**, and the summary dialog's
   760×760 minimum is taller than the main window.
9. **After a ride, the banner shows only the file name.** Show the folder and add an
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

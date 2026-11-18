# Open Items

1. .octw internal format support is not implemented (no parser/writer/schema in code).
2. kJ-based workout completion is not implemented (engine explicitly marks kJ mode as stub). Evidence: workout_engine.py.
3. **CI and release builds.** No GitHub Actions workflows exist yet. Each platform already builds with one command (`scripts\build_windows.cmd`, `scripts/build_linux.sh`; see `packaging/README.md`), so the workflows only need to call them.
    - Add `.github/workflows/release.yml`, triggered by pushing a `v*` tag: a `windows-latest` job running `scripts\build_windows.cmd`, an `ubuntu-latest` job running `scripts/build_linux.sh` (install `flatpak` with apt first, or use the `flatpak/flatpak-github-actions` container), and a final job attaching both `dist/` outputs to the GitHub release (`softprops/action-gh-release` or `gh release upload`).
    - Fail the release if the tag does not match `pyproject.toml`'s version.
    - Optionally run the same builds (with `-SkipTests`/`--skip-tests` after a separate test job) on pushes and pull requests as CI.
    - The MSI is unsigned, so Windows SmartScreen warns about an unknown publisher. Consider code signing (e.g. Azure Trusted Signing) in the Windows job.
    - An aarch64 Flatpak needs an ARM runner (`ubuntu-24.04-arm`).
4. `extend_interval()` in `workout_engine.py` has no upper bound on the extension value. A misbehaving caller could extend an interval to an unreasonable duration. Add a reasonable cap or validation.
5. No end-to-end integration test covering the full workout loop: load workout -> start -> tick -> finish -> FIT file written. Add at least one such test to catch wiring regressions between engine, recorder, and exporter.
6. **Interval transition audio alerts.** Play an audible cue shortly before and at the moment of each interval change, so users don't need to watch the screen during hard efforts.
    - Add an "alert seconds before interval" setting to `AppSettings` (e.g. default 3s, range 0-10s; 0 = disabled). Expose it in the Settings tab.
    - In the workout engine tick (or `WorkoutSessionController`), detect when remaining interval time crosses the configured threshold and when it reaches 0 (transition). Emit a distinct signal for each event - e.g. `interval_warning` and `interval_changed`.
    - In `WorkoutScreen`, connect those signals to a sound-playback slot using PySide6's `QSoundEffect`. Bundle two short audio clips (warning beep, transition chime) in `res/`. Fall back gracefully if audio is unavailable (log a warning, do not crash).
    - Ensure alerts don't fire spuriously on pause/resume or when skipping intervals manually.
7. Add a field to the Builder to add a description to the workout. Read these descriptions out on the right pane in the workout Library when viewing workouts. (Using the standard description field for both MRC and ZWO files)
8. **Publish on Flathub** (which also puts the app in Fedora's Software app when third-party repositories are enabled).
    - Choose a permanent app ID first: `org.opencycletrainer.*` requires owning and verifying opencycletrainer.org; otherwise use `io.github.tbranyon.OpenCycleTrainer`. Renaming later is painful.
    - Add an AppStream `<app-id>.metainfo.xml` (description, screenshots, licence, OARS content rating, releases, homepage) and install it in the manifest; pass `flatpak-builder-lint`.
    - In the Flathub copy of the manifest, replace the local `dir` source with a `git` source pinned to a release tag and commit, and commit the generated `python-deps.json` there.
    - Flathub builds x86_64 and aarch64: extend `packaging/linux/flatpak_deps.py` to emit wheels for both architectures, each marked with `only-arches`.
    - Be ready to justify each `finish-args` permission (Bluetooth/BlueZ for devices, network for Strava/intervals.icu/map tiles, Documents for exports).
    - Submit by pull request to the `new-pr` branch of `flathub/flathub`; later releases are pull requests to the resulting `flathub/<app-id>` repo (automatable with `x-checker-data`).
9. **Crash recovery.** Samples are already streamed to `*.samples.jsonl` during the ride, but nothing looks for orphaned files at startup. Offer to finalize them into a FIT file.
10. **ERG stall protection.** There is no "spiral of death" handling: when cadence collapses under ERG, ease the target and ramp back in.
11. **Record distance and left/right balance in the FIT file.** Balance is decoded (`core/sensors.py:46`) and then dropped; distance can be integrated from speed.
12. **FTP ramp test** that proposes a new FTP. FTP is manual only today, and it drives every percentage-based workout. Needs more definition before implementing (test protocol, how the result is computed, and how it is offered to the user).
13. **Finish or remove half-built pieces:** `core/control/hybrid_mode.py` is unused; the live Hybrid mode runs a separate copy of that logic in `ui/mode_state.py`.
14. **Discard deletes the ride with no confirmation**, and Esc does the same through Qt's default dialog behaviour (`ui/workout_summary_dialog.py:272`, `ui/workout_controller.py:750`). Confirm first; make Esc harmless.
15. **Stop and skip act instantly, and Tab is the skip key.** One stray keypress skips an interval, Tab can no longer move focus, and the hotkeys are not listed anywhere in the app (`ui/hotkeys.py:41`). Rebind skip, confirm Stop, add a "?" overlay.
16. **First run gives no guidance.** Start is visible with nothing loaded and silently does nothing, FTP defaults to 250, and nothing points to Devices. Add a short checklist: pair a trainer, set FTP, pick a workout.
17. **Dark mode is partial.** Banners, builder hints and the summary dialog hard-code colours, although `ui/theme.py` already has a theme-aware palette.
18. **Window size is fixed at 1024×720 and not remembered**, and the summary dialog's 760×760 minimum is taller than the main window.
19. **After a ride, the banner shows only the file name.** Show the folder and add an "Open folder" action.

# Ideas

- **Run the core as a local service** (BLE, engine, recorder) with the UI as a client. A UI crash would no longer end the ride, and a phone could act as a remote or second screen.
- **The UI framework.** `core/`, `devices/`, `storage/` and `integrations/` import no Qt, so a UI swap touches only `ui/` and `app.py`. Options:
    - Stay on PySide6 widgets: nothing to migrate, but scaling, theming and big-number layouts stay manual.
    - Qt Quick (QML) for the ride screen: GPU-drawn, fluid scaling, same Python core and BLE; two UI styles in one app during the transition.
    - Local web UI over the service split above: any phone, tablet or TV becomes the display; browser latency for live charts and packaging a server.
    - Flutter or Tauri rewrite: native mobile apps, but rewrites the BLE layer and FIT export and loses the test suite.

    Earlier recommendation: stay on PySide6 and Python for now; do the service split when a second screen or phone remote becomes a goal, since it makes the UI replaceable without committing to a framework.

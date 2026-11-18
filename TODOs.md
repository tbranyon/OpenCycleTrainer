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

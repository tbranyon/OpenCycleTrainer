# Flatpak Packaging

This directory contains the Linux Flatpak manifest for OpenCycleTrainer.

## Files

- `org.opencycletrainer.OpenCycleTrainer.yaml`: application manifest

The Flatpak build installs bundled app assets to `/app/share/opencycletrainer`:
- Prepackaged workouts in `/app/share/opencycletrainer/workouts`
- In-use icon at `/app/share/opencycletrainer/res/icon_nobg.png`

## Prerequisites

Install Flatpak tooling and add the Flathub remote.

```bash
flatpak remote-add --if-not-exists flathub https://flathub.org/repo/flathub.flatpakrepo
flatpak install flathub org.kde.Platform//6.9 org.kde.Sdk//6.9
```

## Build + Install (local user)

Run from the repository root:

```bash
flatpak-builder --user --install --force-clean .flatpak-builder/build flatpak/org.opencycletrainer.OpenCycleTrainer.yaml
```

## Run

```bash
flatpak run org.opencycletrainer.OpenCycleTrainer
```

## Manifest permissions

- BLE trainer/power-meter communication:
  - `--allow=bluetooth`
  - `--system-talk-name=org.bluez`
  - `--share=network`
- GUI:
  - `--socket=wayland`
  - `--socket=fallback-x11`
  - `--share=ipc`
  - `--device=dri`
- Export target:
  - `--filesystem=xdg-documents`

## Verification checklist

1. Launch app with `flatpak run org.opencycletrainer.OpenCycleTrainer`.
2. Open the Devices tab and confirm BLE scan can discover relevant sensors/trainers.
3. Complete or simulate a recording/export and confirm output can be written to Documents (or app-managed storage).

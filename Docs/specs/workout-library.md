# Workout Library — Feature Spec

## Overview
Add a Workout Library tab that lets users browse, search, and load workouts. Replaces the single "Load Workout" button on the main screen with two separate entry points.

---

## Storage

| Source | Location |
|---|---|
| User-added workouts | Windows: `%APPDATA%\OpenCycleTrainer\workouts\` / Linux: `~/.local/share/opencycletrainer/workouts/` |
| Prepackaged workouts | App install directory `workouts/` subdirectory |

Both directories are scanned when the library is opened. No automatic copying of prepackaged workouts to APPDATA is required.

---

## Main Screen Changes

The existing "Load Workout" button is replaced with two stacked buttons (From Library on top):

- **Load Workout From Library** — navigates to the Workout Library tab
- **Load Workout From File** — opens a file picker (existing behavior, unchanged)

---

## Workout Library Tab

A new top-level tab at the same level as Devices and Settings.

### Workout List

| Column | Value |
|---|---|
| Name | Filename without extension |
| Duration | Total duration parsed from MRC file data |

- Sortable by Name and Duration (click column header to toggle asc/desc)
- Default sort: Name ascending

### Search

- Text input that filters the list by name as the user types (case-insensitive, substring match)
- Clears to show all workouts when empty

### Add to Library

- A button on the library screen opens a file picker
- Selected file is copied into the user workouts directory (`%APPDATA%\OpenCycleTrainer\workouts\` / Linux equivalent)
- List refreshes after copy

### Loading a Workout

- Double-clicking a row loads that workout into the main screen and navigates to the main tab

---

## Out of Scope

- Editing or deleting workouts from the library
- Workout metadata beyond name and duration
- Subfolders / categories
- Copying prepackaged workouts to APPDATA on first run

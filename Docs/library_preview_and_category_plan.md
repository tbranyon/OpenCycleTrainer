# Plan: Workout Library — Preview Pane + Category Column

## Context
Two related library features: (1) restore a single-click preview pane showing a mini chart and estimated stats for the selected workout; (2) add a Category metadata field to MRC files, surface it as a filterable column in the library table, and prompt for category when the user adds a workout manually.

---

## Part A — MRC Parser: `parse_mrc_header` + `inject_category_into_mrc_text`

**File:** `opencycletrainer/core/mrc_parser.py`

Add two new public functions:

```python
def parse_mrc_header(path: str | Path) -> dict[str, str]:
    """Return the [COURSE HEADER] key-value pairs as a lowercase-keyed dict."""
    # Read file, iterate lines inside [COURSE HEADER]...[END COURSE HEADER],
    # split on '=' and collect into dict.
```

```python
def inject_category_into_mrc_text(text: str, category: str) -> str:
    """Insert or replace a CATEGORY line in [COURSE HEADER].
    If CATEGORY already exists, replace it. Otherwise insert it before
    [END COURSE HEADER]. Returns modified text."""
```

**Tests first (`test_mrc_parser.py`):**
- `test_parse_mrc_header_returns_category_value`
- `test_parse_mrc_header_missing_category_returns_empty_via_get`
- `test_parse_mrc_header_no_header_section_returns_empty_dict`
- `test_inject_category_adds_new_line`
- `test_inject_category_replaces_existing`
- `test_inject_category_roundtrips_through_parse`

---

## Part B — Data Models: Category Field

**File:** `opencycletrainer/core/workout_library.py`

- Add `category: str = ""` to `WorkoutLibraryEntry`
- Import `parse_mrc_header` and update `_try_parse` to populate `category = header.get("category", "")`
- Add new method:
  ```python
  def add_workout_from_text(self, text: str, filename: str) -> WorkoutLibraryEntry:
      """Write MRC text directly to user workouts dir and return the entry."""
  ```

**Tests first (`test_workout_library.py`):**
- `test_entry_category_empty_when_no_category_header`
- `test_entry_category_populated_from_mrc_header`
- `test_add_workout_from_text_writes_file_and_returns_entry`
- `test_add_workout_from_text_category_preserved`

---

## Part C — Prepackaged MRC Files: Add CATEGORY Headers

Edit all 16 `.mrc` files in `workouts/` to add `CATEGORY = <value>` before `[END COURSE HEADER]`:

| File | Category |
|------|----------|
| Z2_65_30m.mrc, Z2_65_60m.mrc | Z2 |
| LT1_72_45m.mrc | LT1 |
| Z3_85_2x20.mrc, Z3_85_1x30.mrc | Tempo |
| SST_90_2x20.mrc, SST_90_4x8.mrc, SST_90_3x15.mrc, SST_90_2x25.mrc | SST |
| Z4_95_3x10.mrc, Z4_95_2x20.mrc, Z4_95_4x10.mrc | Threshold |
| KM_Baseline_FTP_Test.mrc | Test |
| VO2_2x3_120-120.mrc, VO2_3x6_60-60.mrc, VO2_3x12_30-30.mrc | VO2max |

**Test first (`test_mrc_parser.py`):** Parametrized test verifying each packaged file returns the correct category from `parse_mrc_header`.

---

## Part D — `workout_chart.py`: Make Two Functions Public

**File:** `opencycletrainer/ui/workout_chart.py`

Rename:
- `_build_target_series` → `build_target_series`
- `_compute_y_max` → `compute_y_max`

Update the two call sites inside `WorkoutChartWidget.load_workout`. Update the import names in `test_workout_chart.py`.

---

## Part E — `workout_library_screen.py`: Full Refactor

**File:** `opencycletrainer/ui/workout_library_screen.py`

### Constructor signature
```python
def __init__(self, library: WorkoutLibrary, ftp_getter: Callable[[], int], parent=None)
```

### Layout change
Replace `root_layout.addWidget(self.table)` with a horizontal `QSplitter`:
- Left: toolbar + 3-column table
- Right: `WorkoutPreviewPane` (new class in same file)
- Initial sizes: 60/40

### Table: 3 columns
`["Category", "Name", "Duration"]` — Category is index 0, Name is index 1 (holds `Qt.UserRole` path), Duration is index 2.

### Toolbar additions
- `QComboBox` (`self.category_combo`) for category filter, between search and Add button
- `_refresh_category_combo()` rebuilds combo from unique non-empty categories in library

### `_populate_table` changes
- Filter by both search text (name) AND category combo selection (ANDed)
- Sort by column: 0=category, 1=name, 2=duration

### `_on_row_double_clicked` / `_on_row_single_clicked`
- Path read from column 1 (Name column holds `Qt.UserRole`)
- Single-click → `self._preview_pane.load(path)`
- Double-click → unchanged signal emit

### `_on_add_clicked` flow
1. `QFileDialog` → `source_path`
2. `_CategoryDialog(existing_cats).exec()`
3. If accepted with a category: `inject_category_into_mrc_text` on file text + `library.add_workout_from_text(text, filename)`
4. If accepted without category (blank): `library.add_workout(source_path)` as before
5. If cancelled: return early
6. `_refresh_category_combo()` + `_populate_table()`

### New class: `_CategoryDialog`
```python
class _CategoryDialog(QDialog):
    """
    QComboBox listing known categories plus an 'Add new...' option.
    Selecting 'Add new...' reveals a QLineEdit for custom text.
    """
    def selected_category(self) -> str:
        """Returns chosen category string, or '' if none selected."""
```

### New class: `WorkoutPreviewPane`
```python
class WorkoutPreviewPane(QWidget):
    def clear(self) -> None:
        """Reset to placeholder state."""

    def load(self, path: Path) -> None:
        """Parse MRC at path using current FTP, populate chart and stats."""
        # parse_mrc_file(path, ftp_watts=self._ftp_getter())
        # build_target_series(workout) → plot
        # compute_y_max + _configure_y_axis
        # _compute_target_np, _compute_target_kj, compute_tss → stat labels
```

Widget layout: name `QLabel` → pyqtgraph `PlotWidget` (fixed height 200px) → 4-stat `QGridLayout` (Duration | Target NP | kJ | TSS)

### New module-level stat functions (pure, no Qt)
```python
def _compute_target_np(workout: Workout) -> int:
    """
    Coggan NP from the target power profile.
    1. Expand intervals to 1-second samples (np.linspace for ramps).
    2. 30-second rolling mean.
    3. mean(rolling^4)^0.25, rounded to int.
    """

def _compute_target_kj(workout: Workout) -> float:
    """
    Total work from target profile.
    kJ = sum((start_w + end_w) / 2 * duration_s / 1000) per interval.
    """
```

`compute_tss` imported from `workout_summary_dialog.py` (already exists).

**Tests first (`test_workout_library_screen.py`):**

*Update existing tests* (column indices shift, `ftp_getter=lambda: 250` added to `_make_screen`):
- `item(r, 0)` → `item(r, 1)` for Name; `item(r, 1)` → `item(r, 2)` for Duration
- Header-click tests emit index 1 (Name) and index 2 (Duration)
- `sectionClicked.emit(1)` for duration sort → `sectionClicked.emit(2)`

*New category tests:*
- `test_table_has_three_columns`
- `test_column_headers_are_category_name_duration`
- `test_category_column_shows_entry_category`
- `test_category_column_empty_when_no_category`
- `test_sort_by_category_column`
- `test_category_filter_combo_initialized_with_all_categories`
- `test_category_filter_filters_table`
- `test_category_filter_all_shows_all_rows`

*New dialog tests:*
- `test_category_dialog_shows_existing_categories_and_add_new`
- `test_category_dialog_text_field_hidden_initially`
- `test_category_dialog_reveals_text_field_on_add_new`
- `test_category_dialog_selected_category_returns_combo_text`
- `test_category_dialog_selected_category_returns_typed_text_on_add_new`
- `test_category_dialog_selected_category_empty_on_blank_selection`

*New preview pane tests:*
- `test_preview_pane_initial_state_shows_placeholder`
- `test_preview_pane_stats_are_dashes_initially`
- `test_preview_pane_load_populates_name_label`
- `test_preview_pane_load_populates_chart_data`
- `test_preview_pane_load_populates_duration_stat`
- `test_preview_pane_load_populates_np_kj_tss_stats`
- `test_preview_pane_clear_resets_all_labels`
- `test_preview_pane_invalid_path_clears_gracefully`
- `test_single_click_row_triggers_preview_load`

*New stat function tests:*
- `test_compute_target_kj_flat_interval`
- `test_compute_target_kj_ramp_interval`
- `test_compute_target_kj_zero_intervals`
- `test_compute_target_np_flat_workout_approximates_power`
- `test_compute_target_np_returns_int`

---

## Part F — `main_window.py`

Update `WorkoutLibraryScreen` construction (~line 78):
```python
self.workout_library_screen = WorkoutLibraryScreen(
    library=self._workout_library,
    ftp_getter=lambda: self._settings.ftp,
    parent=self,
)
```

The lambda closes over `self`, so it always returns the current `_settings.ftp` even after settings updates — no additional wiring needed.

---

## TDD Execution Order

1. **`mrc_parser.py`** — tests + impl for `parse_mrc_header` and `inject_category_into_mrc_text`
2. **`workout_library.py`** — tests + impl for `WorkoutLibraryEntry.category` and `add_workout_from_text`
3. **Prepackaged MRC files** — write parametrized test first (fails), then edit all 16 files
4. **`workout_chart.py`** — update test imports to public names, then rename functions
5. **Stat functions** — tests + impl for `_compute_target_kj` and `_compute_target_np`
6. **`WorkoutPreviewPane`** — tests + impl
7. **`_CategoryDialog` + full screen refactor** — tests + impl for column shift, filter, add-flow
8. **`main_window.py`** — add `ftp_getter`, run full test suite

---

## Verification

- `python -m pytest` — all tests green
- Launch app → Library tab: 3 columns (Category | Name | Duration), category dropdown filters rows
- Single-click a row: right pane shows power chart + Duration / Target NP / kJ / TSS
- Double-click still loads the workout and switches to Workout tab
- "Add to Library" → file picker → category dialog (existing options + "Add new...") → row appears with chosen category
- All prepackaged workouts display their correct categories

# NiceGUI UI Refactor Plan
**OpenCycleTrainer — UI Modernisation**

---

## Table of Contents

1. [Overview & Goals](#overview--goals)
2. [Design System](#design-system)
   - [Colour Palette](#colour-palette)
   - [Typography](#typography)
   - [Spacing & Sizing](#spacing--sizing)
   - [Elevation & Shadows](#elevation--shadows)
   - [Motion & Transitions](#motion--transitions)
   - [Component Tokens](#component-tokens)
3. [Navigation Architecture](#navigation-architecture)
4. [Screen Specifications](#screen-specifications)
   - [App Shell & Sidebar](#app-shell--sidebar)
   - [Workout Screen](#workout-screen)
   - [Library Screen](#library-screen)
   - [Devices Screen](#devices-screen)
   - [Settings Screen](#settings-screen)
   - [Post-Workout Summary Dialog](#post-workout-summary-dialog)
   - [Pause Overlay](#pause-overlay)
5. [Migration Architecture Notes](#migration-architecture-notes)
6. [Implementation Phases](#implementation-phases)

---

## Overview & Goals

**Objective:** Replace the PySide6/Qt UI layer with NiceGUI, running in native window mode (embedded webview). The core logic layer (`core/`, `devices/`, `integrations/`, `storage/`) is unchanged.

**Design Inspiration:** Linear (data-dense, dark-first, precision spacing), Notion (clean cards, generous whitespace), Arc Browser (bold type, vibrant accents, glass-like surfaces).

**Constraints:**
- Desktop-only — no mobile breakpoints required
- Minimum window width: 960px; minimum height: 680px
- No default system/browser widgets exposed
- Must support both dark and light themes, togglable via the Settings screen
- Existing hotkeys (`T`, `1`, `5`, arrows, `Space`, `Tab`) must be preserved

---

## Design System

### Colour Palette

Defined as CSS custom properties on `:root` and overridden for the light theme via a `.light` class on `<html>`. NiceGUI's `ui.add_head_html` injects the stylesheet.

```css
/* ── Dark (default) ─────────────────────────────────────────────── */
:root {
  /* Backgrounds */
  --bg-base:       #0d0d11;   /* outermost canvas */
  --bg-surface:    #15151c;   /* card / panel face */
  --bg-elevated:   #1c1c25;   /* elevated card, dropdown */
  --bg-hover:      #24242f;   /* hover state fill */
  --bg-active:     #2b2b3a;   /* pressed / active */

  /* Borders */
  --border-subtle: #21212d;   /* hairline dividers */
  --border:        #2c2c3c;   /* default border */
  --border-strong: #3e3e54;   /* visible outline */

  /* Text */
  --text-primary:  #eeeef5;
  --text-secondary:#8e8ea8;
  --text-muted:    #56566a;
  --text-disabled: #3e3e52;

  /* Accent — indigo */
  --accent:        #6366f1;
  --accent-hover:  #818cf8;
  --accent-muted:  rgba(99,102,241,0.15);

  /* Semantic */
  --success:       #22c55e;
  --success-muted: rgba(34,197,94,0.12);
  --warning:       #f59e0b;
  --warning-muted: rgba(245,158,11,0.12);
  --error:         #ef4444;
  --error-muted:   rgba(239,68,68,0.12);

  /* Metric / chart colours (unchanged from PyQtGraph palette) */
  --power-target:  #3b82f6;
  --power-actual:  #22c55e;
  --hr-line:       #ef4444;
  --skip-mark:     rgba(234,179,8,0.30);

  /* Sidebar width */
  --sidebar-w: 56px;          /* collapsed (icon-only) */
}

/* ── Light override ─────────────────────────────────────────────── */
html.light {
  --bg-base:       #f5f5fa;
  --bg-surface:    #ffffff;
  --bg-elevated:   #f0f0f8;
  --bg-hover:      #e8e8f2;
  --bg-active:     #dcdcee;

  --border-subtle: #ebebf5;
  --border:        #dcdcea;
  --border-strong: #c4c4d8;

  --text-primary:  #0d0d18;
  --text-secondary:#5a5a72;
  --text-muted:    #9090a8;
  --text-disabled: #b8b8cc;

  --accent:        #4f52e8;
  --accent-hover:  #6366f1;
  --accent-muted:  rgba(79,82,232,0.10);

  --success-muted: rgba(34,197,94,0.10);
  --warning-muted: rgba(245,158,11,0.10);
  --error-muted:   rgba(239,68,68,0.10);
}
```

### Typography

Font loaded via `@import` in the injected stylesheet (bundled with app for offline use or loaded from Google Fonts in dev).

```css
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

:root {
  --font-sans: 'Inter', system-ui, -apple-system, sans-serif;
  --font-mono: 'JetBrains Mono', 'Fira Code', monospace; /* used in metric values */
}

/* Scale */
.text-display  { font-size: 3.25rem; font-weight: 700; line-height: 1;    letter-spacing: -0.02em; }
.text-metric   { font-size: 2.5rem;  font-weight: 600; line-height: 1.1;  font-family: var(--font-mono); }
.text-h1       { font-size: 1.375rem;font-weight: 600; line-height: 1.3;  }
.text-h2       { font-size: 1.0rem;  font-weight: 600; line-height: 1.4;  }
.text-body     { font-size: 0.875rem;font-weight: 400; line-height: 1.5;  }
.text-small    { font-size: 0.75rem; font-weight: 400; line-height: 1.4;  }
.text-label    { font-size: 0.6875rem;font-weight:500; letter-spacing:0.06em; text-transform: uppercase; }
```

**Rule:** Metric tile values use `--font-mono` to prevent layout jitter when numbers change. All other copy uses Inter.

### Spacing & Sizing

Base unit = **4 px**. All spacing values are multiples of this.

| Token | Value | Usage |
|-------|-------|-------|
| `--space-1` | 4px | Icon padding, tight gaps |
| `--space-2` | 8px | Inline element gaps |
| `--space-3` | 12px | Card inner padding (compact) |
| `--space-4` | 16px | Default card padding |
| `--space-5` | 20px | Section gaps |
| `--space-6` | 24px | Panel padding |
| `--space-8` | 32px | Major section breaks |
| `--space-12` | 48px | Screen padding top/bottom |

**Border radius:**

| Token | Value | Usage |
|-------|-------|-------|
| `--r-sm` | 4px | Badges, tooltips, small chips |
| `--r-md` | 8px | Inputs, small cards |
| `--r-lg` | 12px | Metric tiles, panels |
| `--r-xl` | 16px | Large cards, sheet backgrounds |
| `--r-full` | 9999px | Pills, avatar, circular buttons |

### Elevation & Shadows

```css
:root {
  /* Dark mode — shadows are more opaque because bg is already dark */
  --shadow-card:    0 1px 2px rgba(0,0,0,0.5), 0 0 0 1px var(--border-subtle);
  --shadow-raised:  0 4px 14px rgba(0,0,0,0.55);
  --shadow-dialog:  0 24px 64px rgba(0,0,0,0.70);
  --shadow-glow-accent: 0 0 0 3px var(--accent-muted);   /* focus ring */
}
html.light {
  --shadow-card:    0 1px 3px rgba(0,0,0,0.07), 0 0 0 1px var(--border-subtle);
  --shadow-raised:  0 4px 14px rgba(0,0,0,0.09);
  --shadow-dialog:  0 24px 64px rgba(0,0,0,0.16);
}
```

### Motion & Transitions

Avoid animation during live workout updates (performance). Use transitions only on interactive state changes.

```css
:root {
  --ease-out:   cubic-bezier(0.16, 1, 0.3, 1);
  --ease-snappy: cubic-bezier(0.4, 0, 0.2, 1);
  --duration-fast: 100ms;
  --duration-base: 160ms;
  --duration-slow: 260ms;
}

/* Default interactive element transition */
.interactive {
  transition: background-color var(--duration-fast) var(--ease-snappy),
              border-color     var(--duration-fast) var(--ease-snappy),
              box-shadow       var(--duration-base) var(--ease-snappy);
}
```

### Component Tokens

```css
/* Buttons */
--btn-h:        36px;          /* standard button height */
--btn-h-sm:     28px;
--btn-h-lg:     44px;
--btn-px:       14px;          /* horizontal padding */
--btn-r:        var(--r-md);
--btn-font:     0.875rem;
--btn-weight:   500;

/* Inputs */
--input-h:      36px;
--input-px:     12px;
--input-r:      var(--r-md);
--input-bg:     var(--bg-elevated);
--input-border: var(--border);

/* Metric tiles */
--tile-r:       var(--r-lg);
--tile-bg:      var(--bg-surface);
--tile-shadow:  var(--shadow-card);
--tile-pad:     var(--space-4);
```

---

## Navigation Architecture

The app shell is a full-viewport flex layout:

```
┌─────────────────────────────────────────────────────────────────┐
│  Sidebar (56px)  │  Content area (flex-1)                       │
│                  │                                               │
│  [logo]          │  ┌── screen header ──────────────────────┐   │
│  ──────          │  │  Title           [actions]            │   │
│  [ride icon]  ◄  │  └────────────────────────────────────────┘  │
│  [library]       │                                               │
│  [devices]       │  ┌── main content ───────────────────────┐   │
│  ──────          │  │                                        │   │
│  [settings]      │  │                                        │   │
│                  │  │                                        │   │
│  ──────          │  └────────────────────────────────────────┘  │
│  [theme toggle]  │                                               │
└──────────────────┴───────────────────────────────────────────────┘
```

- Sidebar is always visible; icon-only at 56px (no expand/collapse in v1)
- Active nav item: accent-coloured left border `3px solid var(--accent)` + `var(--bg-active)` fill
- Hover: `var(--bg-hover)` background, transition 100ms
- Theme toggle sits at the bottom of the sidebar — sun/moon icon
- Logo: `icon_nobg_small.png` at 28px, centred above nav items

**NiceGUI implementation:** `ui.left_drawer` with custom CSS override (disable default Quasar drawer styles entirely), or plain `ui.element('aside')` with CSS positioning.

---

## Screen Specifications

### App Shell & Sidebar

**File:** `ui/shell.py` (new)

```
Sidebar item anatomy:
  ┌─────────────────────────┐
  │  [3px accent border]    │
  │  [icon 20px]            │  40px tall touch target
  │                         │
  └─────────────────────────┘
```

| Element | Style |
|---------|-------|
| Sidebar background | `var(--bg-surface)` + right border `1px var(--border)` |
| Nav icon | Phosphor Icons or Lucide, 20px, `var(--text-secondary)` default, `var(--text-primary)` active |
| Active item | Left border 3px `var(--accent)`, background `var(--bg-active)` |
| Hover item | Background `var(--bg-hover)` |
| Tooltip | Dark pill on hover: `var(--bg-elevated)` + `--shadow-raised`, 200ms delay |
| Theme toggle | Icon-only button at bottom; rotates 180° on click (CSS transform) |

**Nav items (top to bottom):**
1. Ride (bicycle icon) — WorkoutScreen
2. Library (list icon) — LibraryScreen
3. Devices (bluetooth icon) — DevicesScreen
4. Settings (sliders icon) — SettingsScreen

---

### Workout Screen

**File:** `ui/workout_screen.py` (refactored)

This is the most complex screen. Layout uses CSS Grid for the main area:

```
┌──────────────────────────────────────────────────────────────────┐
│  WORKOUT SCREEN                                                  │
│                                                                  │
│  ┌─ Load section ───────────────────────────────────────────┐   │
│  │  [Open File]  [From Library]    filename.mrc             │   │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                  │
│  ┌─ Mandatory metrics (4 tiles, equal width) ───────────────┐   │
│  │ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐     │   │
│  │ │ Elapsed  │ │ Target W │ │ Interval │ │ Remaining│     │   │
│  │ │  0:00    │ │  ---     │ │  0:00    │ │  0:00    │     │   │
│  │ └──────────┘ └──────────┘ └──────────┘ └──────────┘     │   │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                  │
│  ┌─ Configurable tiles (up to 8, 4-per-row) ────────────────┐   │
│  │  [ tile ]  [ tile ]  [ tile ]  [ tile ]                  │   │
│  │  [ tile ]  [ tile ]  [ tile ]  [ tile ]                  │   │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                  │
│  ┌─ Charts (stacked) ────────────────────────────────────────┐  │
│  │  [──── Interval chart (60% height) ────────────────────]  │  │
│  │  [──── Overview chart  (40% height) ───────────────────]  │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                  │
│  ┌─ Controls ────────────────────────────────────────────────┐  │
│  │    [Start]  [Pause]  [Resume]  [Stop]    [alert banner]  │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                  │
│  ┌─ Trainer footer ──────────────────────────────────────────┐  │
│  │  Mode: [ERG ▾]   Resistance: +0%   OpenTrueUp: +0W       │  │
│  └───────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
```

#### Metric Tile Component

Each tile is a reusable card:

```
┌──────────────────────┐
│  ELAPSED             │  ← .text-label, var(--text-muted)
│                      │
│  1:23:45             │  ← .text-metric, var(--text-primary)
│                      │
│  ── subtext ──       │  ← .text-small, var(--text-secondary) [optional]
└──────────────────────┘
```

| Property | Value |
|----------|-------|
| Background | `var(--tile-bg)` |
| Border | `1px solid var(--border)` |
| Radius | `var(--r-lg)` |
| Shadow | `var(--shadow-card)` |
| Padding | `var(--space-4)` |
| Min width | 120px |
| Value font | `--font-mono`, `--text-metric` (2.5rem) |
| Label font | `--text-label` (0.6875rem uppercase, muted) |

**Active state (target power tile while workout running):** thin `2px solid var(--accent)` border, `var(--accent-muted)` background tint.

#### Control Buttons

| Button | Variant | Visibility condition |
|--------|---------|---------------------|
| Start | Primary (filled accent) | IDLE or READY |
| Pause | Secondary (outlined) | RUNNING |
| Resume | Primary | PAUSED |
| Stop | Destructive (error-tinted) | RUNNING or PAUSED |

Button anatomy:
```css
.btn-primary {
  background: var(--accent);
  color: #fff;
  border: none;
  border-radius: var(--btn-r);
  height: var(--btn-h);
  padding: 0 var(--btn-px);
  font-size: var(--btn-font);
  font-weight: var(--btn-weight);
  cursor: pointer;
}
.btn-primary:hover { background: var(--accent-hover); }
.btn-primary:active { transform: scale(0.97); }

.btn-secondary {
  background: transparent;
  color: var(--text-primary);
  border: 1px solid var(--border-strong);
}
.btn-secondary:hover { background: var(--bg-hover); }

.btn-destructive {
  background: var(--error-muted);
  color: var(--error);
  border: 1px solid rgba(239,68,68,0.30);
}
.btn-destructive:hover { background: rgba(239,68,68,0.20); }
```

#### Alert Banner

Replaces the current `QLabel` alert. Slides in from top with `transform: translateY(-4px) → translateY(0)`, opacity 0 → 1.

```
┌─────────────────────────────────────────────────────────────┐
│  ⚠  Failed to write FIT file.                    [×]        │
└─────────────────────────────────────────────────────────────┘
```

| Type | Text colour | Background | Border-left |
|------|------------|-----------|-------------|
| error | `var(--error)` | `var(--error-muted)` | `3px solid var(--error)` |
| success | `var(--success)` | `var(--success-muted)` | `3px solid var(--success)` |
| warning | `var(--warning)` | `var(--warning-muted)` | `3px solid var(--warning)` |

Auto-dismiss: 5s (unchanged). Manual dismiss: [×] button.

#### Trainer Mode Footer

A slim bar at the bottom of the screen content area:

```
ERG  ▾        Resistance offset:  ─────●─────  +3%        OpenTrueUp: +12W
```

- Background: `var(--bg-surface)`, top border `1px var(--border)`
- Height: 48px
- Mode selector: custom `<select>` styled with CSS — no system widget
- Resistance slider: custom NiceGUI `ui.slider` with Tailwind/CSS override, accent thumb

---

### Library Screen

**File:** `ui/library_screen.py` (refactored)

```
┌──────────────────────────────────────────────────────────────────┐
│  Library                           [+ Add to Library]           │
│                                                                  │
│  ┌─ Search ────────────────────────────────────────────────┐    │
│  │  🔍  Search workouts...                                  │    │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ┌─ Table ─────────────────────────────────────────────────┐    │
│  │  Name ↕                Duration ↕        Actions        │    │
│  │  ──────────────────────────────────────────────────────  │    │
│  │  Vo2Max Intervals       1:05:00         [Load]          │    │
│  │  Sweet Spot Base         0:55:00        [Load]          │    │
│  │  …                                                       │    │
│  └──────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────┘
```

| Element | Style |
|---------|-------|
| Search input | Full-width, `var(--input-h)`, icon prefix (magnifier SVG), `var(--input-bg)`, `var(--r-md)` |
| Table header | `var(--bg-elevated)`, sticky top, `--text-label` style, cursor pointer on sortable cols |
| Table row | `var(--bg-surface)`, hover → `var(--bg-hover)` |
| Row border | `1px solid var(--border-subtle)` bottom |
| Selected row | `var(--accent-muted)` background |
| Load button | `btn-secondary` small variant (`--btn-h-sm`) |
| Empty state | Centred icon + label + "Add workouts to your library" |

**NiceGUI:** `ui.table` with custom CSS override. Columns: `name`, `duration`. Row actions via slot.

---

### Devices Screen

**File:** `ui/devices_screen.py` (refactored)

```
┌──────────────────────────────────────────────────────────────────┐
│  Devices                          [Scan]  Backend: [Bleak ▾]    │
│                                                                  │
│  ── Paired Devices ─────────────────────────────────────────    │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ Name          Type       Status     Battery  Reading     │   │
│  │ ─────────────────────────────────────────────────────── │   │
│  │ Kickr Core    Trainer    ● Connected  82%    250W  [Cal] │   │
│  │ HR Belt       HR Mon     ● Connected  --     144bpm      │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ── Available Devices ──────────────────────────────────────    │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ CycleOps Mag  Power     ○ Discovered  --    --   [Pair]  │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│  Scanning for devices…                                           │
└──────────────────────────────────────────────────────────────────┘
```

| Element | Style |
|---------|-------|
| Section label | `--text-label` with `1px solid var(--border)` ruled line extending right |
| Status badge (connected) | Green dot `var(--success)` + "Connected" text, pill shape `var(--r-full)`, `var(--success-muted)` bg |
| Status badge (discovered) | Muted dot `var(--text-muted)` + "Discovered" |
| Status badge (connecting) | Amber dot + pulsing CSS animation |
| Battery pill | `var(--bg-elevated)` pill; if ≤20% → amber tint |
| [Pair] button | `btn-secondary` small |
| [Cal] button | `btn-secondary` small, only shown when `supports_calibration` |
| [Unpair] button | `btn-destructive` small (icon only — trash) |
| Scan button | `btn-primary`, transforms to "Stop Scan" with spinner while scanning |
| Spinner animation | Pure CSS `@keyframes` spin, no library dependency |

---

### Settings Screen

**File:** `ui/settings_screen.py` (refactored)

Organised into collapsible sections (open by default). Each section is a card.

```
┌──────────────────────────────────────────────────────────────────┐
│  Settings                                       [Save Changes]  │
│                                                                  │
│  ▾ General ─────────────────────────────────────────────────    │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  FTP (W)              [───250───]    50–2000             │   │
│  │  Lead Time (s)        [─────0───]    0–30                │   │
│  │  Power Window (s)     [─────3───]    1–10                │   │
│  │  OpenTrueUp           [toggle]                           │   │
│  │  Units                [Metric ▾]                         │   │
│  │  Default Mode         [Workout ▾]                        │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ▾ Metric Tiles ─────────────────────────────────────────────   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  Select up to 8 tiles (6 of 8 selected)                  │   │
│  │  ☑ Power    ☑ Cadence  ☑ HR      ☑ Speed                │   │
│  │  ☑ Avg Pwr  ☑ NP      ☐ TSS     ☐ Avg Spd              │   │
│  │  ☐ kJ       ☐ Avg HR  ☐ % FTP                           │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ▾ Strava ──────────────────────────────────────────────────    │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  Status: Connected as John Doe                           │   │
│  │  [Disconnect]   Auto-sync [toggle]   [Sync Now]          │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ▾ Display ─────────────────────────────────────────────────    │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  Theme        [Dark ▾]                                   │   │
│  └──────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────┘
```

| Element | Style |
|---------|-------|
| Section header | `--text-h2`, chevron icon rotates on collapse, bottom border `var(--border)` |
| Card | `var(--bg-surface)`, `var(--r-xl)`, `var(--shadow-card)`, padding `var(--space-6)` |
| Number input | Custom spinner — system arrow buttons hidden via CSS. +/- icon buttons on either side |
| Toggle | Custom CSS toggle: pill track `var(--bg-elevated)`, thumb `#fff`; checked → track `var(--accent)` |
| Checkbox | Custom square with rounded corner `var(--r-sm)`, checked → `var(--accent)` fill with checkmark SVG |
| Tile count badge | `N of 8 selected` in small pill, changes to amber when over limit |
| Dropdown | Custom `<select>` wrapper with chevron icon, `var(--input-bg)`, no system chevron |
| Save button | `btn-primary`, full right-align, disabled + faded while no changes pending |
| Status message | Appears below Save; success → green inline badge, error → red |

---

### Post-Workout Summary Dialog

**File:** `ui/workout_summary_dialog.py` (refactored)

Presented as a centred modal with backdrop blur.

```
            ┌───────────────────────────────────┐
            │                                   │
            │   Great Ride! 🎉                 │
            │   Zone 3 Build — 1 hr 15 min     │
            │                                   │
            │  ┌────────┐ ┌────────┐ ┌───────┐ │
            │  │ 1:15:34│ │ 623kJ │ │ 247W  │ │
            │  │ Elapsed│ │ Work  │ │  NP   │ │
            │  └────────┘ └────────┘ └───────┘ │
            │  ┌─────────────┐ ┌────────────┐  │
            │  │   72.4      │ │   144 bpm  │  │
            │  │    TSS      │ │   Avg HR   │  │
            │  └─────────────┘ └────────────┘  │
            │                                   │
            │   [Upload to Strava]   [Close]    │
            │                                   │
            └───────────────────────────────────┘
```

| Element | Style |
|---------|-------|
| Backdrop | `rgba(0,0,0,0.65)`, `backdrop-filter: blur(4px)` |
| Dialog card | `var(--bg-elevated)`, `var(--r-xl)`, `var(--shadow-dialog)`, max-width 480px |
| Title | `--text-h1`, centred |
| Subtitle (workout name + duration) | `--text-secondary`, `--text-small` |
| Metric tiles | Same tile component, compact variant (padding `var(--space-3)`, value `1.75rem`) |
| Tile grid | 3-column, then 2-column for remaining stats |
| Upload button | `btn-primary`; transforms to "Uploading…" spinner while in progress; "Uploaded ✓" on success |
| Close button | `btn-secondary` |
| Enter / Escape hotkeys | Close dialog |

---

### Pause Overlay

**File:** `ui/pause_overlay.py` (refactored; replaces `PauseDialog`)

Full-screen overlay rather than a dialog — takes over the entire content area to avoid distraction.

```
┌──────────────────────────────────────────────────────────────────┐
│                                                                  │
│                                                                  │
│                        PAUSED                                    │
│                    ─────────────                                 │
│                       0:45:12                                    │
│                     elapsed so far                               │
│                                                                  │
│              Resuming in  3                                      │
│                                                                  │
│          [Resume Now]         [Stop Workout]                     │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

| Element | Style |
|---------|-------|
| Overlay background | `var(--bg-base)` at 94% opacity, `backdrop-filter: blur(12px)` |
| "PAUSED" heading | `--text-display`, `var(--text-muted)`, `--text-label` style (uppercase, tracked) |
| Countdown number | `4rem`, monospace, `var(--accent)`, fade-transition between ticks |
| Elapsed | Secondary colour, `--text-metric` size |
| Buttons | Standard `btn-primary` / `btn-destructive` pair |
| Appearance animation | Content block fades in + `translateY(8px → 0)` over 200ms |

---

## Migration Architecture Notes

### Event Loop

NiceGUI uses **asyncio** as its event loop. The existing Bleak BLE backend (`devices/ble_backend.py`) already uses asyncio, making it compatible without changes. The PySide6 `QThread` usage in `WorkoutSessionController` (OAuth flow, recorder) must be replaced with `asyncio.create_task()` or `run_in_executor` for blocking I/O.

### Signals → NiceGUI Events

| PySide6 pattern | NiceGUI replacement |
|----------------|---------------------|
| `Signal` / `emit()` | Python callable callbacks, `ui.timer` polling |
| `QTimer` (periodic) | `ui.timer(interval, callback)` |
| `QThread` (background) | `asyncio.create_task()` |
| `QDialog.exec()` (modal) | `ui.dialog()` context manager |
| `QFileDialog` | `ui.upload` or `app.native.main_window` file picker hook |
| Widget `setVisible()` | `element.set_visibility()` or conditional rendering |

### State Management

Replace Qt's reactive signal system with explicit refresh calls. The `WorkoutSessionController` will expose a snapshot method; a `ui.timer` at ~10Hz calls it and updates all live metric labels via `label.set_text()`. Chart data is pushed via ECharts `chart.run_javascript()` or NiceGUI's `echart.options` mutation.

### Charts: PyQtGraph → ECharts

ECharts chart instances are created with `ui.echart(options)`. Data is pushed by mutating the `options` dict and calling `chart.update()`. The dual-chart layout (interval + overview) maps naturally to two separate `ui.echart` elements stacked vertically.

Custom axis formatter for MM:SS:
```js
formatter: function(val) {
  const m = Math.floor(val / 60);
  const s = String(Math.floor(val % 60)).padStart(2, '0');
  return m + ':' + s;
}
```

### Keyboard Shortcuts

Replace `WorkoutHotkeys` (QKeyEvent filter) with a JavaScript snippet injected via `ui.add_body_html` or `app.on_connect`:
```js
document.addEventListener('keydown', (e) => {
  if (['INPUT','TEXTAREA','SELECT'].includes(document.activeElement.tagName)) return;
  // Map keys to websocket emits
});
```
Use NiceGUI's `app.on_connect` to inject the listener and `ui.on('keydown', handler)` to receive it server-side.

### Packaging

`app.native` mode requires `pywebview`. Add to `requirements.txt`. The Flatpak manifest and Windows NSIS spec will need `nicegui`, `pywebview`, and removal of `PySide6`, `PyQtGraph` dependencies.

### File Picker

NiceGUI's native window mode exposes `app.native.main_window` which wraps `pywebview`. File dialogs are available via `webview.create_file_dialog()`. Wrap this in a helper that falls back gracefully.

---

## Implementation Phases

Token estimates are for Claude Sonnet 4.x; each phase estimate covers ~context sent + output written. Phases assume sequential implementation within one session each (except Phase 0 which is a setup phase).

---

### Phase 0 — Foundation & Design System

**Scope:**
- Add `nicegui` and `pywebview` to dependencies; remove `PySide6`, `PyQtGraph`
- Create `ui/theme.py` — CSS custom properties injected via `ui.add_head_html`; Inter font; base reset; token definitions for dark + light
- Create `ui/components.py` — shared Python/NiceGUI component functions: `metric_tile()`, `section_header()`, `badge()`, `alert_banner()`, `confirm_dialog()`
- Migrate `app.py` to NiceGUI `app.native` startup
- Theme toggle: JS snippet + CSS class flip on `<html>`, persisted to `AppSettings`
- Update `requirements.txt`, `flatpak` manifest, Windows NSIS spec

**Deliverables:** App launches as native window; blank white/dark canvas with correct sidebar shell renders; theme toggle works.

**Estimated tokens:** ~18 000

---

### Phase 1 — App Shell & Sidebar Navigation

**Scope:**
- `ui/shell.py` — sidebar `<aside>`, nav items with icon + tooltip, logo
- Page routing: `ui.navigate.to()` between 4 page paths
- Active state CSS logic
- Keyboard shortcut JS listener skeleton (server-side handler stubs)
- Screen header component (title + right-side action slot)

**Deliverables:** Full sidebar renders; clicking nav items routes to placeholder pages.

**Estimated tokens:** ~14 000

---

### Phase 2 — Workout Screen (Static Layout)

**Scope:**
- Port `ui/workout_screen.py` to NiceGUI
- Mandatory metric tiles row (4 tiles)
- Configurable tile grid (up to 8, 4-per-row)
- Control button row with correct visibility/enable logic per engine state
- Alert banner component (all 3 types, auto-dismiss)
- Trainer mode footer (mode selector, resistance display, OpenTrueUp display)
- Load file section (file picker integration)
- Pause overlay page layer

**Deliverables:** Full static workout screen renders; buttons and tiles visible; no live data yet.

**Estimated tokens:** ~28 000

---

### Phase 3 — Workout Controller Wiring

**Scope:**
- Refactor `ui/workout_controller.py`: replace `QTimer` with `ui.timer`, `QThread` with `asyncio.create_task`
- Wire engine state changes → UI visibility updates (start/pause/resume/stop buttons)
- Wire engine snapshot → metric tile `set_text()` calls at 10Hz
- Wire alert callbacks → `alert_banner()` component
- Wire keyboard shortcuts → workout actions
- Pause overlay countdown logic
- Post-workout summary dialog trigger

**Deliverables:** App can run a workout end-to-end with all metrics updating live; pause/resume/stop works; hotkeys work.

**Estimated tokens:** ~32 000

---

### Phase 4 — Live Charts (ECharts)

**Scope:**
- Replace `ui/workout_chart.py` with ECharts-based implementation
- Interval chart: target fill, actual power line, HR line, FTP dashed reference, position cursor
- Overview chart: full workout target fill, actual power trace, skip markers (yellow fills), HR line
- MM:SS axis formatters
- Dark/light theme-aware chart colours (ECharts theme object, switched on toggle)
- Real-time update: push new data points via `chart.run_javascript()` or options mutation at 1Hz for overview, 2Hz for interval

**Deliverables:** Both charts render with correct colours; update smoothly during a workout; skip markers appear; theme switches without page reload.

**Estimated tokens:** ~26 000

---

### Phase 5 — Library Screen

**Scope:**
- Port `ui/workout_library_screen.py` to NiceGUI
- Searchable `ui.table` with custom row/cell styling
- Sortable columns (name, duration)
- [Load] row action routes to workout screen with selected workout pre-loaded
- "Add to Library" file picker
- Empty state illustration

**Deliverables:** Library screen fully functional; search, sort, load all work.

**Estimated tokens:** ~12 000

---

### Phase 6 — Devices Screen

**Scope:**
- Port `ui/devices_screen.py` to NiceGUI
- Paired and Available device tables with status badges, battery pills, action buttons
- Scan button with spinner + "Stop Scan" toggle
- Backend selector (Mock/Bleak)
- BLE async wiring: scan results → table update via `ui.timer` polling device manager state
- Calibration action trigger and feedback

**Deliverables:** Device discovery, pairing, and connection works; tables update in real time.

**Estimated tokens:** ~22 000

---

### Phase 7 — Settings Screen

**Scope:**
- Port `ui/settings_screen.py` to NiceGUI
- Custom number inputs (±buttons, no system spinners)
- Custom toggle switches and checkboxes (pure CSS)
- Tile selector grid with count badge and max-8 enforcement
- Collapsible section cards
- Strava section: OAuth button, status, disconnect, auto-sync toggle, Sync Now
- Theme selector wired to theme toggle logic
- Save / discard behaviour; unsaved changes indicator

**Deliverables:** All settings persist correctly; Strava OAuth flow works; tile selector enforces limits.

**Estimated tokens:** ~24 000

---

### Phase 8 — Post-Workout Dialog & Polish

**Scope:**
- Port `ui/workout_summary_dialog.py` to NiceGUI modal
- Compact metric tile variant in dialog grid
- Strava upload button with inline progress state
- Global polish pass: review all screens for spacing consistency, hover states, focus rings, transition timing
- Accessibility: ARIA labels on icon-only buttons, focus trap in dialogs, keyboard nav through form fields
- Regression test review: ensure existing pytest suite still passes (core unchanged); add any new smoke tests for UI component logic

**Deliverables:** Summary dialog works; all screens are visually consistent and accessible; tests pass.

**Estimated tokens:** ~20 000

---

### Token Budget Summary

| Phase | Scope | Estimated Tokens |
|-------|-------|-----------------|
| 0 | Foundation, design system, CSS, app entry | ~18 000 |
| 1 | Shell, sidebar, routing | ~14 000 |
| 2 | Workout screen static layout | ~28 000 |
| 3 | Workout controller wiring (live data) | ~32 000 |
| 4 | Live charts (ECharts) | ~26 000 |
| 5 | Library screen | ~12 000 |
| 6 | Devices screen | ~22 000 |
| 7 | Settings screen | ~24 000 |
| 8 | Summary dialog + polish + tests | ~20 000 |
| **Total** | | **~196 000** |

> **Note:** These estimates assume each phase is implemented in a fresh context window with necessary file contents provided. Phases 2 and 3 are the highest-risk phases due to the complexity of `workout_controller.py` (983 LOC) and the async model migration; budget additional tokens if significant rework is needed. Phases can be parallelised (e.g. Phase 5 and Phase 6 are independent of each other).

---

*Plan authored 2026-03-14.*

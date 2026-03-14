"""Design system: CSS custom properties, typography, and theme injection for NiceGUI."""
from __future__ import annotations

from nicegui import ui

# ── CSS ───────────────────────────────────────────────────────────────────────

_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;600&display=swap');

/* ── Design tokens ──────────────────────────────────────────────────────── */
:root {
  --font-sans: 'Inter', system-ui, -apple-system, sans-serif;
  --font-mono: 'JetBrains Mono', 'Fira Code', monospace;

  /* Spacing (4px base) */
  --space-1:  4px;
  --space-2:  8px;
  --space-3:  12px;
  --space-4:  16px;
  --space-5:  20px;
  --space-6:  24px;
  --space-8:  32px;
  --space-12: 48px;

  /* Border radius */
  --r-sm:   4px;
  --r-md:   8px;
  --r-lg:   12px;
  --r-xl:   16px;
  --r-full: 9999px;

  /* Easing */
  --ease-out:    cubic-bezier(0.16, 1, 0.3, 1);
  --ease-snappy: cubic-bezier(0.4, 0, 0.2, 1);
  --dur-fast: 100ms;
  --dur-base: 160ms;
  --dur-slow: 260ms;

  /* Button tokens */
  --btn-h:    36px;
  --btn-h-sm: 28px;
  --btn-h-lg: 44px;
  --btn-px:   14px;
  --btn-r:    var(--r-md);

  /* Layout */
  --sidebar-w: 56px;

  /* Metric / chart colours — consistent across themes */
  --power-target: #3b82f6;
  --power-actual: #22c55e;
  --hr-line:      #ef4444;
  --skip-mark:    rgba(234, 179, 8, 0.30);
}

/* ── Dark theme (default) ───────────────────────────────────────────────── */
:root,
html.dark {
  color-scheme: dark;

  --bg-base:       #0d0d11;
  --bg-surface:    #15151c;
  --bg-elevated:   #1c1c25;
  --bg-hover:      #24242f;
  --bg-active:     #2b2b3a;

  --border-subtle: #21212d;
  --border:        #2c2c3c;
  --border-strong: #3e3e54;

  --text-primary:   #eeeef5;
  --text-secondary: #8e8ea8;
  --text-muted:     #56566a;
  --text-disabled:  #3e3e52;

  --accent:       #6366f1;
  --accent-hover: #818cf8;
  --accent-muted: rgba(99, 102, 241, 0.15);

  --success:       #22c55e;
  --success-muted: rgba(34, 197, 94, 0.12);
  --warning:       #f59e0b;
  --warning-muted: rgba(245, 158, 11, 0.12);
  --error:         #ef4444;
  --error-muted:   rgba(239, 68, 68, 0.12);

  --shadow-card:        0 1px 2px rgba(0,0,0,0.50), 0 0 0 1px var(--border-subtle);
  --shadow-raised:      0 4px 14px rgba(0,0,0,0.55);
  --shadow-dialog:      0 24px 64px rgba(0,0,0,0.70);
  --shadow-glow-accent: 0 0 0 3px var(--accent-muted);
}

/* ── Light theme ────────────────────────────────────────────────────────── */
html.light {
  color-scheme: light;

  --bg-base:       #f5f5fa;
  --bg-surface:    #ffffff;
  --bg-elevated:   #f0f0f8;
  --bg-hover:      #e8e8f2;
  --bg-active:     #dcdcee;

  --border-subtle: #ebebf5;
  --border:        #dcdcea;
  --border-strong: #c4c4d8;

  --text-primary:   #0d0d18;
  --text-secondary: #5a5a72;
  --text-muted:     #9090a8;
  --text-disabled:  #b8b8cc;

  --accent:       #4f52e8;
  --accent-hover: #6366f1;
  --accent-muted: rgba(79, 82, 232, 0.10);

  --success-muted: rgba(34, 197, 94, 0.10);
  --warning-muted: rgba(245, 158, 11, 0.10);
  --error-muted:   rgba(239, 68, 68, 0.10);

  --shadow-card:        0 1px 3px rgba(0,0,0,0.07), 0 0 0 1px var(--border-subtle);
  --shadow-raised:      0 4px 14px rgba(0,0,0,0.09);
  --shadow-dialog:      0 24px 64px rgba(0,0,0,0.16);
  --shadow-glow-accent: 0 0 0 3px var(--accent-muted);
}

/* ── Base reset ─────────────────────────────────────────────────────────── */
*, *::before, *::after {
  box-sizing: border-box;
}

html, body {
  height: 100%;
  margin: 0;
  padding: 0;
  background: var(--bg-base);
  color: var(--text-primary);
  font-family: var(--font-sans);
  font-size: 14px;
  line-height: 1.5;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}

/* Override NiceGUI / Quasar layout defaults */
.q-layout, .q-page-container, .q-page {
  background: var(--bg-base) !important;
  min-height: 100vh;
}
.q-page-container { padding: 0 !important; }
.q-layout__shadow { display: none !important; }

/* ── Typography utilities ───────────────────────────────────────────────── */
.text-display {
  font-size: 3.25rem; font-weight: 700; line-height: 1; letter-spacing: -0.02em;
}
.text-metric {
  font-size: 2.5rem; font-weight: 600; line-height: 1.1;
  font-family: var(--font-mono);
}
.text-h1  { font-size: 1.375rem; font-weight: 600; line-height: 1.3; }
.text-h2  { font-size: 1.0rem;   font-weight: 600; line-height: 1.4; }
.text-body { font-size: 0.875rem; font-weight: 400; line-height: 1.5; }
.text-small { font-size: 0.75rem; font-weight: 400; line-height: 1.4; }
.text-label {
  font-size: 0.6875rem; font-weight: 500;
  letter-spacing: 0.06em; text-transform: uppercase;
}

.color-primary   { color: var(--text-primary)   !important; }
.color-secondary { color: var(--text-secondary) !important; }
.color-muted     { color: var(--text-muted)     !important; }
.color-accent    { color: var(--accent)         !important; }
.color-success   { color: var(--success)        !important; }
.color-error     { color: var(--error)          !important; }
.color-warning   { color: var(--warning)        !important; }

/* ── App shell ──────────────────────────────────────────────────────────── */
.app-shell {
  display: flex;
  height: 100vh;
  width: 100vw;
  overflow: hidden;
  background: var(--bg-base);
}

/* ── Sidebar ────────────────────────────────────────────────────────────── */
.sidebar {
  width: var(--sidebar-w);
  height: 100vh;
  display: flex;
  flex-direction: column;
  align-items: center;
  background: var(--bg-surface);
  border-right: 1px solid var(--border);
  flex-shrink: 0;
  padding: var(--space-3) 0;
  z-index: 100;
}

.sidebar-logo {
  width: 28px;
  height: 28px;
  margin-bottom: var(--space-2);
  opacity: 0.9;
  border-radius: var(--r-sm);
}

.sidebar-divider {
  width: 32px;
  height: 1px;
  background: var(--border);
  margin: var(--space-1) 0;
  flex-shrink: 0;
}

.sidebar-spacer { flex: 1; }

.nav-item {
  position: relative;
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  height: 40px;
  cursor: pointer;
  color: var(--text-secondary);
  border-left: 3px solid transparent;
  transition:
    background-color var(--dur-fast) var(--ease-snappy),
    color            var(--dur-fast) var(--ease-snappy),
    border-color     var(--dur-fast) var(--ease-snappy);
}
.nav-item:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}
.nav-item.active {
  background: var(--bg-active);
  color: var(--text-primary);
  border-left-color: var(--accent);
}
.nav-item .q-icon { font-size: 20px !important; }

/* ── Content area ───────────────────────────────────────────────────────── */
.content-area {
  flex: 1;
  height: 100vh;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  background: var(--bg-base);
}

/* ── Screen header ──────────────────────────────────────────────────────── */
.screen-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-5) var(--space-6);
  border-bottom: 1px solid var(--border);
  background: var(--bg-surface);
  flex-shrink: 0;
}
.screen-header-title {
  font-size: 1.375rem;
  font-weight: 600;
  color: var(--text-primary);
}
.screen-header-actions {
  display: flex;
  gap: var(--space-2);
  align-items: center;
}

/* ── Buttons ────────────────────────────────────────────────────────────── */
.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  height: var(--btn-h);
  padding: 0 var(--btn-px);
  border-radius: var(--btn-r);
  font-size: 0.875rem;
  font-weight: 500;
  font-family: var(--font-sans);
  cursor: pointer;
  border: none;
  outline: none;
  text-decoration: none;
  white-space: nowrap;
  user-select: none;
  transition:
    background-color var(--dur-fast) var(--ease-snappy),
    border-color     var(--dur-fast) var(--ease-snappy),
    transform        var(--dur-fast) var(--ease-snappy),
    box-shadow       var(--dur-base) var(--ease-snappy);
}
.btn:active { transform: scale(0.97); }
.btn:focus-visible { box-shadow: var(--shadow-glow-accent); }

.btn-sm { height: var(--btn-h-sm); padding: 0 10px; font-size: 0.75rem; }
.btn-lg { height: var(--btn-h-lg); padding: 0 20px; font-size: 1rem; }

.btn-primary {
  background: var(--accent);
  color: #ffffff;
}
.btn-primary:hover { background: var(--accent-hover); }

.btn-secondary {
  background: transparent;
  color: var(--text-primary);
  border: 1px solid var(--border-strong);
}
.btn-secondary:hover { background: var(--bg-hover); }

.btn-destructive {
  background: var(--error-muted);
  color: var(--error);
  border: 1px solid rgba(239, 68, 68, 0.30);
}
.btn-destructive:hover { background: rgba(239, 68, 68, 0.20); }

.btn-ghost {
  background: transparent;
  color: var(--text-secondary);
}
.btn-ghost:hover { background: var(--bg-hover); color: var(--text-primary); }

/* Override Quasar button chrome */
.q-btn {
  border-radius: var(--btn-r) !important;
  font-family: var(--font-sans) !important;
  text-transform: none !important;
  letter-spacing: 0 !important;
}
.q-btn__content { font-weight: 500 !important; }
.q-btn.btn-primary { background: var(--accent) !important; color: #fff !important; }
.q-btn.btn-primary:hover { background: var(--accent-hover) !important; }
.q-btn .q-ripple { display: none !important; }  /* disable ripple for custom look */

/* ── Cards ──────────────────────────────────────────────────────────────── */
.card {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--r-xl);
  box-shadow: var(--shadow-card);
  padding: var(--space-6);
}
.card-sm {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--r-lg);
  box-shadow: var(--shadow-card);
  padding: var(--space-4);
}

/* ── Metric tile ────────────────────────────────────────────────────────── */
.metric-tile {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--r-lg);
  box-shadow: var(--shadow-card);
  padding: var(--space-4);
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  min-width: 120px;
  transition:
    border-color     var(--dur-base) var(--ease-snappy),
    background-color var(--dur-base) var(--ease-snappy),
    box-shadow       var(--dur-base) var(--ease-snappy);
}
.metric-tile.active {
  border-color: var(--accent);
  background: color-mix(in srgb, var(--bg-surface) 85%, var(--accent) 15%);
}
.metric-tile-label {
  font-size: 0.6875rem;
  font-weight: 500;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--text-muted);
}
.metric-tile-value {
  font-size: 2.5rem;
  font-weight: 600;
  line-height: 1.1;
  font-family: var(--font-mono);
  color: var(--text-primary);
}
.metric-tile-sub { font-size: 0.75rem; color: var(--text-secondary); }

/* Compact variant for dialogs */
.metric-tile-compact { padding: var(--space-3); }
.metric-tile-compact .metric-tile-value { font-size: 1.75rem; }

/* ── Section header ─────────────────────────────────────────────────────── */
.section-header {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin-bottom: var(--space-4);
}
.section-header-label {
  font-size: 0.6875rem;
  font-weight: 500;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--text-muted);
  white-space: nowrap;
}
.section-header-rule {
  flex: 1;
  height: 1px;
  background: var(--border);
}

/* ── Badge ──────────────────────────────────────────────────────────────── */
.badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  border-radius: var(--r-full);
  font-size: 0.6875rem;
  font-weight: 500;
}
.badge-success { background: var(--success-muted); color: var(--success); }
.badge-error   { background: var(--error-muted);   color: var(--error); }
.badge-warning { background: var(--warning-muted); color: var(--warning); }
.badge-neutral { background: var(--bg-elevated);   color: var(--text-secondary); }

/* ── Status dot ─────────────────────────────────────────────────────────── */
.status-dot {
  width: 7px; height: 7px;
  border-radius: 50%;
  flex-shrink: 0;
  display: inline-block;
}
.status-dot-success { background: var(--success); }
.status-dot-error   { background: var(--error); }
.status-dot-neutral { background: var(--text-muted); }
.status-dot-warning {
  background: var(--warning);
  animation: status-pulse 1.5s ease-in-out infinite;
}
@keyframes status-pulse {
  0%, 100% { opacity: 1; }
  50%       { opacity: 0.4; }
}

/* ── Alert banner ───────────────────────────────────────────────────────── */
.alert-banner {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  border-radius: var(--r-md);
  font-size: 0.875rem;
  animation: alert-in var(--dur-base) var(--ease-out);
}
.alert-banner-error {
  background: var(--error-muted);
  color: var(--error);
  border-left: 3px solid var(--error);
}
.alert-banner-success {
  background: var(--success-muted);
  color: var(--success);
  border-left: 3px solid var(--success);
}
.alert-banner-warning {
  background: var(--warning-muted);
  color: var(--warning);
  border-left: 3px solid var(--warning);
}
@keyframes alert-in {
  from { opacity: 0; transform: translateY(-4px); }
  to   { opacity: 1; transform: translateY(0); }
}

/* ── Tooltip override ───────────────────────────────────────────────────── */
.q-tooltip {
  font-size: 0.75rem !important;
  font-family: var(--font-sans) !important;
  background: var(--bg-elevated) !important;
  color: var(--text-primary) !important;
  border: 1px solid var(--border) !important;
  box-shadow: var(--shadow-raised) !important;
  border-radius: var(--r-sm) !important;
  padding: 4px 8px !important;
}

/* ── Form controls ──────────────────────────────────────────────────────── */
.q-field__control {
  background: var(--bg-elevated) !important;
  border-radius: var(--r-md) !important;
}
.q-field__native, .q-field__input {
  color: var(--text-primary) !important;
  font-family: var(--font-sans) !important;
}
.q-field--outlined .q-field__control::before {
  border-color: var(--border) !important;
}
.q-field--outlined:hover .q-field__control::before {
  border-color: var(--border-strong) !important;
}
.q-field--focused .q-field__control::after {
  border-color: var(--accent) !important;
}
.q-field__label { color: var(--text-secondary) !important; font-family: var(--font-sans) !important; }

/* ── Tables ─────────────────────────────────────────────────────────────── */
.q-table__card {
  background: var(--bg-surface) !important;
  border: 1px solid var(--border) !important;
  border-radius: var(--r-xl) !important;
  box-shadow: var(--shadow-card) !important;
}
.q-table thead tr th {
  background: var(--bg-elevated) !important;
  color: var(--text-muted) !important;
  font-size: 0.6875rem !important;
  font-weight: 500 !important;
  letter-spacing: 0.06em !important;
  text-transform: uppercase !important;
  border-bottom: 1px solid var(--border) !important;
  font-family: var(--font-sans) !important;
}
.q-table tbody tr td {
  color: var(--text-primary) !important;
  border-bottom: 1px solid var(--border-subtle) !important;
  font-size: 0.875rem !important;
  font-family: var(--font-sans) !important;
}
.q-table tbody tr:hover td { background: var(--bg-hover) !important; }

/* ── Dialogs ────────────────────────────────────────────────────────────── */
.q-dialog__backdrop {
  background: rgba(0, 0, 0, 0.65) !important;
  backdrop-filter: blur(4px) !important;
}
.q-card {
  background: var(--bg-elevated) !important;
  border-radius: var(--r-xl) !important;
  box-shadow: var(--shadow-dialog) !important;
  border: 1px solid var(--border) !important;
  color: var(--text-primary) !important;
}

/* ── Scrollbar ──────────────────────────────────────────────────────────── */
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb {
  background: var(--border-strong);
  border-radius: var(--r-full);
}
::-webkit-scrollbar-thumb:hover { background: var(--text-muted); }

/* ── Spinner ────────────────────────────────────────────────────────────── */
@keyframes spin { to { transform: rotate(360deg); } }
.spinner {
  display: inline-block;
  width: 16px; height: 16px;
  border: 2px solid var(--border-strong);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
}

/* ── Placeholder page ───────────────────────────────────────────────────── */
.placeholder-page {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--space-4);
  padding: var(--space-12);
}
.placeholder-icon { font-size: 48px !important; color: var(--text-muted) !important; opacity: 0.4; }
.placeholder-label { font-size: 1rem; font-weight: 500; color: var(--text-muted); }
.placeholder-sub   { font-size: 0.875rem; color: var(--text-disabled); }
"""


def inject(theme: str = "dark") -> None:
    """Inject design-system CSS and set the initial theme class on <html>.

    Must be called once per page render (inside a NiceGUI page handler).
    """
    ui.add_head_html(f"<style>{_CSS}</style>")
    # Set class before body paint to prevent flash of wrong theme.
    cls = "light" if theme == "light" else "dark"
    ui.add_head_html(
        f'<script>document.documentElement.className = "{cls}";</script>'
    )

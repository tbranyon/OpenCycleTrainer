"""App shell: sidebar navigation, theme toggle, and page layout builder."""
from __future__ import annotations

from nicegui import ui

from .. import state
from .theme import inject

# Nav item definitions: (route, Material Icon name, tooltip label)
_NAV_ITEMS: list[tuple[str, str, str]] = [
    ("/workout",  "directions_bike", "Ride"),
    ("/library",  "menu_book",       "Library"),
    ("/devices",  "bluetooth",       "Devices"),
    ("/settings", "tune",            "Settings"),
]

# JavaScript injected once per page to wire keyboard shortcuts.
# Actual server-side handlers are registered in each page module.
_HOTKEYS_JS = """
(function () {
  if (window._octHotkeysAttached) return;
  window._octHotkeysAttached = true;
  document.addEventListener('keydown', function (e) {
    const tag = document.activeElement ? document.activeElement.tagName : '';
    if (['INPUT', 'TEXTAREA', 'SELECT'].includes(tag)) return;
    emitEvent('hotkey', { key: e.key, code: e.code, shift: e.shiftKey, alt: e.altKey });
  });
})();
"""


def build(active_route: str) -> ui.element:
    """Render the full app shell and return the content-area element.

    Call this once at the top of every page handler.  All page-specific
    content should be placed inside the returned element via a ``with`` block::

        content = shell.build('/workout')
        with content:
            ui.label('Hello')
    """
    settings = state.get()
    is_dark = settings.theme == "dark"

    # Inject design-system CSS and set initial theme class on <html>
    inject(settings.theme)

    # Quasar dark-mode element — keeps Quasar internals in sync
    dark_mode = ui.dark_mode(value=is_dark)

    # Keyboard shortcuts JS (idempotent guard inside the script)
    ui.add_body_html(f"<script>{_HOTKEYS_JS}</script>")

    with ui.element("div").classes("app-shell"):
        _build_sidebar(active_route, dark_mode, is_dark)
        content = ui.element("main").classes("content-area")

    return content


def _build_sidebar(
    active_route: str,
    dark_mode: ui.dark_mode,
    is_dark: bool,
) -> None:
    """Render the fixed left sidebar with nav items and theme toggle."""
    with ui.element("aside").classes("sidebar"):
        # Logo
        ui.image("/res/icon_nobg_small.png").classes("sidebar-logo")
        ui.element("div").classes("sidebar-divider")

        # Navigation items
        for route, icon_name, label in _NAV_ITEMS:
            _nav_item(route, icon_name, label, active=(route == active_route))

        ui.element("div").classes("sidebar-spacer")
        ui.element("div").classes("sidebar-divider")

        # Theme toggle
        theme_icon = "light_mode" if is_dark else "dark_mode"
        theme_tip = "Switch to light mode" if is_dark else "Switch to dark mode"
        with ui.element("div").classes("nav-item").props(
            f'role="button" aria-label="{theme_tip}" tabindex="0"'
        ) as toggle_btn:
            ui.icon(theme_icon).classes("color-secondary")
            ui.tooltip(theme_tip)
        toggle_btn.on("click", lambda: _toggle_theme(dark_mode))


def _nav_item(route: str, icon_name: str, label: str, *, active: bool) -> None:
    """Render a single sidebar navigation item."""
    cls = "nav-item active" if active else "nav-item"
    with ui.element("div").classes(cls).props(
        f'role="link" aria-label="{label}" tabindex="0"'
    ) as item:
        ui.icon(icon_name)
        ui.tooltip(label)
    item.on("click", lambda r=route: ui.navigate.to(r))


def _toggle_theme(dark_mode: ui.dark_mode) -> None:
    """Flip the theme, persist it, and update the page without a reload."""
    current = state.get().theme
    new_theme = "light" if current == "dark" else "dark"
    state.update(theme=new_theme)
    dark_mode.set_value(new_theme == "dark")
    cls = new_theme  # "dark" or "light"
    ui.run_javascript(f'document.documentElement.className = "{cls}";')

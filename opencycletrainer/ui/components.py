"""Reusable NiceGUI UI components for OpenCycleTrainer."""
from __future__ import annotations

from nicegui import ui


class MetricTile:
    """A card displaying a labelled metric value with an optional sub-line.

    The value label can be updated at runtime via :meth:`set_value`.
    Pass *active=True* to highlight with the accent border (e.g. current target).
    """

    def __init__(
        self,
        label: str,
        initial_value: str = "---",
        sub: str = "",
        active: bool = False,
        compact: bool = False,
    ) -> None:
        base_class = "metric-tile"
        if compact:
            base_class += " metric-tile-compact"
        if active:
            base_class += " active"

        with ui.element("div").classes(base_class) as self.container:
            ui.label(label).classes("metric-tile-label")
            self._value_label = ui.label(initial_value).classes("metric-tile-value")
            if sub:
                self._sub_label: ui.label | None = ui.label(sub).classes("metric-tile-sub")
            else:
                self._sub_label = None

    def set_value(self, value: str) -> None:
        """Update the displayed value."""
        self._value_label.set_text(value)

    def set_sub(self, text: str) -> None:
        """Update the sub-label text (if one was provided at construction)."""
        if self._sub_label is not None:
            self._sub_label.set_text(text)

    def set_active(self, active: bool) -> None:
        """Toggle the accent-highlighted active state."""
        if active:
            self.container.classes(add="active")
        else:
            self.container.classes(remove="active")


def section_header(label: str) -> None:
    """Render a labelled horizontal divider used to introduce a group of elements."""
    with ui.element("div").classes("section-header"):
        ui.label(label).classes("section-header-label")
        ui.element("div").classes("section-header-rule")


def badge(text: str, variant: str = "neutral") -> ui.element:
    """Render a small status pill.

    *variant* is one of ``"success"``, ``"error"``, ``"warning"``, ``"neutral"``.
    """
    cls = f"badge badge-{variant}"
    return ui.label(text).classes(cls)


def status_badge(text: str, variant: str = "neutral") -> None:
    """Render a status pill with a coloured dot prefix (for device status etc.)."""
    dot_cls = f"status-dot status-dot-{variant}"
    with ui.element("div").classes(f"badge badge-{variant}"):
        ui.element("span").classes(dot_cls)
        ui.label(text)


class AlertBanner:
    """An inline alert banner (error / success / warning) with auto-dismiss.

    Call :meth:`show` to display a message and :meth:`hide` to clear it.
    Auto-dismisses after *timeout_s* seconds when *timeout_s* > 0.
    """

    _ICON = {"error": "error_outline", "success": "check_circle_outline", "warning": "warning_amber"}

    def __init__(self, timeout_s: float = 5.0) -> None:
        self._timeout_s = timeout_s
        self._timer: ui.timer | None = None

        with ui.element("div") as self.container:
            self._inner = ui.element("div").classes("alert-banner alert-banner-error")
            with self._inner:
                self._icon = ui.icon("error_outline")
                self._text = ui.label("")
                ui.element("div").style("flex:1")
                ui.button(icon="close", on_click=self.hide).classes("btn btn-ghost btn-sm")
        self.container.set_visibility(False)

    def show(self, message: str, kind: str = "error") -> None:
        """Display *message* with the given *kind* (``'error'``, ``'success'``, ``'warning'``)."""
        self._inner.classes(
            replace=f"alert-banner alert-banner-{kind}"
        )
        self._icon.props(f'name="{self._ICON.get(kind, "info")}"')
        self._text.set_text(message)
        self.container.set_visibility(True)
        if self._timer:
            self._timer.cancel()
        if self._timeout_s > 0:
            self._timer = ui.timer(self._timeout_s, self.hide, once=True)

    def hide(self) -> None:
        """Dismiss the banner."""
        self.container.set_visibility(False)
        if self._timer:
            self._timer.cancel()
            self._timer = None


def screen_header(title: str) -> ui.element:
    """Render the standard screen header bar and return the actions slot container."""
    with ui.element("div").classes("screen-header"):
        ui.label(title).classes("screen-header-title")
        actions = ui.element("div").classes("screen-header-actions")
    return actions


def confirm_dialog(
    title: str,
    message: str,
    confirm_label: str = "Confirm",
    cancel_label: str = "Cancel",
    destructive: bool = False,
) -> ui.dialog:
    """Return a NiceGUI dialog with confirm/cancel buttons.

    Caller should open it with ``dialog.open()`` and connect to the
    ``on_value_change`` event to detect the result, or use ``await dialog``
    in an async handler.
    """
    with ui.dialog() as dialog, ui.card().style("min-width: 360px; gap: 16px"):
        ui.label(title).classes("text-h1 color-primary")
        ui.label(message).classes("text-body color-secondary")
        with ui.element("div").style("display:flex; gap:8px; justify-content:flex-end"):
            ui.button(cancel_label, on_click=lambda: dialog.submit(False)).classes(
                "btn btn-secondary"
            ).props("no-caps flat")
            confirm_cls = "btn btn-destructive" if destructive else "btn btn-primary"
            ui.button(confirm_label, on_click=lambda: dialog.submit(True)).classes(
                confirm_cls
            ).props("no-caps")
    return dialog

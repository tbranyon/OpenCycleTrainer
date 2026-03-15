"""Devices page — Phase 6: full device management screen."""
from __future__ import annotations

from nicegui import ui

from .. import shell
from ..devices_screen_ng import DevicesController, DevicesScreenNg
from ... import singletons


@ui.page("/devices")
def devices_page() -> None:
    """Device management screen: scan, pair, connect, and calibrate BLE devices."""
    content = shell.build("/devices")

    backend = singletons.get_device_manager()
    controller = DevicesController(backend)

    # Propagate trainer device changes to the workout controller
    controller.register_trainer_changed_callback(singletons.notify_trainer_changed)

    def _on_backend_changed(backend_name: str) -> None:
        if backend_name == "Mock":
            from opencycletrainer.devices.mock_backend import MockDeviceBackend  # noqa: PLC0415
            new_backend = MockDeviceBackend()
        else:
            try:
                from opencycletrainer.devices.ble_backend import BleakDeviceBackend  # noqa: PLC0415
                from opencycletrainer.storage.paired_devices import PairedDeviceStore  # noqa: PLC0415
                new_backend = BleakDeviceBackend(paired_device_store=PairedDeviceStore())
            except Exception:
                from opencycletrainer.devices.mock_backend import MockDeviceBackend  # noqa: PLC0415
                new_backend = MockDeviceBackend()
        controller.switch_backend(new_backend)
        singletons.set_device_manager(new_backend)

    with content:
        DevicesScreenNg(controller=controller, on_backend_changed=_on_backend_changed)

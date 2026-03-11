from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from concurrent.futures import Future
from dataclasses import replace
import inspect
import threading
from typing import Any

from .device_manager import AsyncioRunner, DeviceManager, NotificationCallback, completed_future
from .types import (
    DeviceInfo,
    DeviceType,
    NOTIFICATION_CHARACTERISTIC_UUIDS,
    infer_device_type,
)


class BleakDeviceBackend(DeviceManager):
    """Bleak-powered device manager with async scan/connect/notify plumbing."""

    def __init__(self, scan_timeout_seconds: float = 5.0) -> None:
        self._scan_timeout_seconds = scan_timeout_seconds
        self._runner = AsyncioRunner()
        self._lock = threading.Lock()
        self._devices: dict[str, DeviceInfo] = {}
        self._paired_ids: set[str] = set()
        self._clients: dict[str, Any] = {}

    def scan(self) -> Future[list[DeviceInfo]]:
        return self._runner.submit(self._scan_async())

    def get_paired_devices(self) -> list[DeviceInfo]:
        with self._lock:
            paired = [device for device in self._devices.values() if device.paired]
            return sorted(paired, key=lambda device: device.name.lower())

    def get_available_devices(self) -> list[DeviceInfo]:
        with self._lock:
            available = [device for device in self._devices.values() if not device.paired]
            return sorted(available, key=lambda device: device.name.lower())

    def pair_device(self, device_id: str) -> Future[None]:
        with self._lock:
            device = self._get_device(device_id)
            self._paired_ids.add(device_id)
            self._devices[device_id] = replace(device, paired=True)
        return completed_future(None)

    def unpair_device(self, device_id: str) -> Future[None]:
        return self._runner.submit(self._unpair_async(device_id))

    def connect_device(self, device_id: str) -> Future[None]:
        return self._runner.submit(self._connect_async(device_id))

    def disconnect_device(self, device_id: str) -> Future[None]:
        return self._runner.submit(self._disconnect_async(device_id))

    def calibrate_device(self, device_id: str) -> Future[bool]:
        self._get_device(device_id)
        return completed_future(False)

    def subscribe_device_notifications(
        self,
        device_id: str,
        callback: NotificationCallback,
    ) -> Future[None]:
        return self._runner.submit(self._subscribe_notifications_async(device_id, callback))

    def shutdown(self) -> None:
        try:
            self._runner.submit(self._disconnect_all_async()).result(timeout=5.0)
        except Exception:
            pass
        self._runner.shutdown()

    async def _scan_async(self) -> list[DeviceInfo]:
        _, scanner = self._load_bleak_classes()
        discovered = await scanner.discover(timeout=self._scan_timeout_seconds, return_adv=True)
        scanned_devices: list[DeviceInfo] = []

        if isinstance(discovered, dict):
            iterable = discovered.values()
        else:
            iterable = ((device, None) for device in discovered)

        for entry in iterable:
            ble_device, advertisement = entry
            service_uuids = self._extract_service_uuids(ble_device, advertisement)
            device_type = infer_device_type(service_uuids)
            if device_type is None:
                continue

            device_id = getattr(ble_device, "address", None) or getattr(ble_device, "name", None)
            if not device_id:
                continue

            name = getattr(ble_device, "name", None) or "Unknown Device"
            rssi = getattr(advertisement, "rssi", None)
            if rssi is None:
                rssi = getattr(ble_device, "rssi", None)

            with self._lock:
                existing = self._devices.get(device_id)
                is_connected = device_id in self._clients
                is_paired = device_id in self._paired_ids
                info = DeviceInfo(
                    device_id=device_id,
                    name=name,
                    device_type=device_type,
                    address=getattr(ble_device, "address", None),
                    rssi=rssi,
                    paired=is_paired,
                    connected=is_connected,
                    battery_percent=existing.battery_percent if existing else None,
                    supports_calibration=(
                        existing.supports_calibration
                        if existing
                        else device_type is DeviceType.POWER_METER
                    ),
                )
                self._devices[device_id] = info
                scanned_devices.append(info)

        return sorted(scanned_devices, key=lambda device: device.name.lower())

    async def _unpair_async(self, device_id: str) -> None:
        if device_id in self._clients:
            await self._disconnect_async(device_id)
        with self._lock:
            device = self._get_device(device_id)
            self._paired_ids.discard(device_id)
            self._devices[device_id] = replace(device, paired=False, connected=False)

    async def _connect_async(self, device_id: str) -> None:
        client_cls, _ = self._load_bleak_classes()
        with self._lock:
            device = self._get_device(device_id)
            address = device.address or device.device_id
            existing_client = self._clients.get(device_id)
        if existing_client is not None and getattr(existing_client, "is_connected", False):
            return

        client = client_cls(address)
        await client.connect()

        with self._lock:
            refreshed = self._get_device(device_id)
            self._clients[device_id] = client
            self._devices[device_id] = replace(refreshed, connected=True)

    async def _disconnect_async(self, device_id: str) -> None:
        with self._lock:
            client = self._clients.get(device_id)
        if client is not None:
            await client.disconnect()
        with self._lock:
            self._clients.pop(device_id, None)
            device = self._get_device(device_id)
            self._devices[device_id] = replace(device, connected=False)

    async def _disconnect_all_async(self) -> None:
        with self._lock:
            device_ids = list(self._clients.keys())
        for device_id in device_ids:
            await self._disconnect_async(device_id)

    async def _subscribe_notifications_async(
        self,
        device_id: str,
        callback: NotificationCallback,
    ) -> None:
        with self._lock:
            client = self._clients.get(device_id)
        if client is None or not getattr(client, "is_connected", False):
            raise RuntimeError(f"Device {device_id} is not connected")

        for characteristic_uuid in NOTIFICATION_CHARACTERISTIC_UUIDS:
            try:
                await client.start_notify(
                    characteristic_uuid,
                    self._build_notification_handler(
                        device_id=device_id,
                        characteristic_uuid=characteristic_uuid,
                        callback=callback,
                    ),
                )
            except Exception:
                continue

    def _build_notification_handler(
        self,
        device_id: str,
        characteristic_uuid: str,
        callback: NotificationCallback,
    ) -> Any:
        async def _dispatch(payload: bytes) -> None:
            callback_result = callback(device_id, characteristic_uuid, payload)
            if isinstance(callback_result, Awaitable):
                await callback_result

        def _handler(_: Any, data: bytearray) -> None:
            payload = bytes(data)
            dispatch = _dispatch(payload)
            if inspect.isawaitable(dispatch):
                asyncio.create_task(dispatch)

        return _handler

    def _get_device(self, device_id: str) -> DeviceInfo:
        if device_id not in self._devices:
            raise KeyError(f"Unknown device id: {device_id}")
        return self._devices[device_id]

    @staticmethod
    def _extract_service_uuids(ble_device: Any, advertisement: Any) -> list[str]:
        from_advertisement = list(getattr(advertisement, "service_uuids", None) or [])
        if from_advertisement:
            return from_advertisement
        metadata = getattr(ble_device, "metadata", {}) or {}
        from_metadata = metadata.get("uuids")
        return list(from_metadata or [])

    @staticmethod
    def _load_bleak_classes() -> tuple[type[Any], type[Any]]:
        try:
            from bleak import BleakClient, BleakScanner
        except ImportError as exc:
            raise RuntimeError(
                "Bleak backend requires the 'bleak' package. Install dependencies with 'pip install -e .'."
            ) from exc
        return BleakClient, BleakScanner

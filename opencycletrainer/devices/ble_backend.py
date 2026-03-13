from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from concurrent.futures import Future
from dataclasses import replace
import inspect
import threading
from typing import Any

from .device_manager import AsyncioRunner, DeviceManager, NotificationCallback, completed_future
from .types import (
    CPS_CONTROL_POINT_CHARACTERISTIC_UUID,
    DeviceInfo,
    DeviceType,
    FTMS_CONTROL_POINT_CHARACTERISTIC_UUID,
    NOTIFICATION_CHARACTERISTIC_UUIDS,
    infer_device_type,
)
from opencycletrainer.storage.paired_devices import PairedDeviceStore

PayloadNotificationCallback = Callable[[bytes], Awaitable[None] | None]

START_OFFSET_COMP_OPCODE = 0x0C

class BleakDeviceBackend(DeviceManager):
    """Bleak-powered device manager with async scan/connect/notify plumbing."""

    def __init__(
        self,
        scan_timeout_seconds: float = 5.0,
        paired_device_store: PairedDeviceStore | None = None,
    ) -> None:
        self._scan_timeout_seconds = scan_timeout_seconds
        self._paired_device_store = paired_device_store if paired_device_store is not None else PairedDeviceStore()
        self._runner = AsyncioRunner()
        self._lock = threading.Lock()
        self._devices: dict[str, DeviceInfo] = {}
        self._paired_ids: set[str] = set()
        self._clients: dict[str, Any] = {}
        self._load_paired_ids_from_store()

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
        self._persist_paired_ids()
        return completed_future(None)

    def unpair_device(self, device_id: str) -> Future[None]:
        return self._runner.submit(self._unpair_async(device_id))

    def connect_device(self, device_id: str) -> Future[None]:
        return self._runner.submit(self._connect_async(device_id))

    def disconnect_device(self, device_id: str) -> Future[None]:
        return self._runner.submit(self._disconnect_async(device_id))

    def calibrate_device(self, device_id: str) -> Future[int | None]:
        return self._runner.submit(self._calibrate_async(device_id))

    def subscribe_device_notifications(
        self,
        device_id: str,
        callback: NotificationCallback,
    ) -> Future[None]:
        return self._runner.submit(self._subscribe_notifications_async(device_id, callback))

    def write_gatt_characteristic(
        self,
        device_id: str,
        characteristic_uuid: str,
        payload: bytes,
        *,
        response: bool = True,
    ) -> Future[None]:
        return self._runner.submit(
            self._write_gatt_characteristic_async(
                device_id,
                characteristic_uuid,
                payload,
                response=response,
            ),
        )

    def subscribe_characteristic(
        self,
        device_id: str,
        characteristic_uuid: str,
        callback: PayloadNotificationCallback,
    ) -> Future[None]:
        return self._runner.submit(
            self._subscribe_characteristic_async(
                device_id,
                characteristic_uuid,
                callback,
            ),
        )

    def write_ftms_control_point(self, device_id: str, payload: bytes) -> Future[None]:
        return self.write_gatt_characteristic(
            device_id,
            FTMS_CONTROL_POINT_CHARACTERISTIC_UUID,
            payload,
            response=True,
        )

    def subscribe_ftms_control_point_indications(
        self,
        device_id: str,
        callback: PayloadNotificationCallback,
    ) -> Future[None]:
        return self.subscribe_characteristic(
            device_id,
            FTMS_CONTROL_POINT_CHARACTERISTIC_UUID,
            callback,
        )

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

        for device_id in self._paired_ids:
            if device_id not in self._clients:
                try:
                    await self._connect_async(device_id)
                except Exception:
                    pass

        return sorted(scanned_devices, key=lambda device: device.name.lower())

    async def _unpair_async(self, device_id: str) -> None:
        if device_id in self._clients:
            await self._disconnect_async(device_id)
        with self._lock:
            device = self._get_device(device_id)
            self._paired_ids.discard(device_id)
            self._devices[device_id] = replace(device, paired=False, connected=False)
        self._persist_paired_ids()

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
            for uuid in NOTIFICATION_CHARACTERISTIC_UUIDS:
                try:
                    await client.stop_notify(uuid)
                except Exception:
                    pass
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

    async def _calibrate_async(self, device_id: str) -> int | None:
        with self._lock:
            device = self._get_device(device_id)
            client = self._clients.get(device_id)
        if device.device_type is not DeviceType.POWER_METER:
            raise RuntimeError(f"Device {device_id} does not support calibration")
        if client is None or not getattr(client, "is_connected", False):
            raise RuntimeError(f"Device {device_id} is not connected")

        # Subscribe to CPS Control Point indications to capture the offset response.
        indication_event = asyncio.Event()
        response_payload: list[bytes] = []

        def _indication_handler(_: Any, data: bytearray) -> None:
            if not response_payload:
                response_payload.append(bytes(data))
                indication_event.set()

        indication_subscribed = False
        try:
            try:
                await client.start_notify(CPS_CONTROL_POINT_CHARACTERISTIC_UUID, _indication_handler)
                indication_subscribed = True
            except Exception:
                pass

            # Cycling Power Control Point opcode 0x0C = Start Offset Compensation (zero-offset)
            await client.write_gatt_char(
                CPS_CONTROL_POINT_CHARACTERISTIC_UUID,
                bytearray([START_OFFSET_COMP_OPCODE]),
                response=True,
            )

            if indication_subscribed:
                try:
                    await asyncio.wait_for(indication_event.wait(), timeout=8.0)
                except asyncio.TimeoutError:
                    return None

                # CPS Control Point response format:
                # [0] 0x20 (Response Code), [1] 0x0C (request opcode), [2] result (0x01=success),
                # [3:5] offset int16 LE (optional)
                if response_payload:
                    data = response_payload[0]
                    if len(data) >= 3 and data[0] == 0x20 and data[1] == START_OFFSET_COMP_OPCODE and data[2] == 0x01:
                        if len(data) >= 5:
                            return int.from_bytes(data[3:5], "little", signed=True)
            return None
        finally:
            if indication_subscribed:
                try:
                    await client.stop_notify(CPS_CONTROL_POINT_CHARACTERISTIC_UUID)
                except Exception:
                    pass

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

    async def _write_gatt_characteristic_async(
        self,
        device_id: str,
        characteristic_uuid: str,
        payload: bytes,
        *,
        response: bool,
    ) -> None:
        with self._lock:
            client = self._clients.get(device_id)
        if client is None or not getattr(client, "is_connected", False):
            raise RuntimeError(f"Device {device_id} is not connected")
        await client.write_gatt_char(
            characteristic_uuid,
            bytearray(payload),
            response=response,
        )

    async def _subscribe_characteristic_async(
        self,
        device_id: str,
        characteristic_uuid: str,
        callback: PayloadNotificationCallback,
    ) -> None:
        with self._lock:
            client = self._clients.get(device_id)
        if client is None or not getattr(client, "is_connected", False):
            raise RuntimeError(f"Device {device_id} is not connected")
        await client.start_notify(
            characteristic_uuid,
            self._build_payload_notification_handler(callback),
        )

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
                self._schedule_awaitable(dispatch)

        return _handler

    def _build_payload_notification_handler(
        self,
        callback: PayloadNotificationCallback,
    ) -> Any:
        async def _dispatch(payload: bytes) -> None:
            callback_result = callback(payload)
            if isinstance(callback_result, Awaitable):
                await callback_result

        def _handler(_: Any, data: bytearray) -> None:
            payload = bytes(data)
            dispatch = _dispatch(payload)
            if inspect.isawaitable(dispatch):
                self._schedule_awaitable(dispatch)

        return _handler

    @staticmethod
    def _schedule_awaitable(dispatch: Awaitable[None]) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(dispatch)
            return
        loop.create_task(dispatch)

    def _load_paired_ids_from_store(self) -> None:
        """Populate _paired_ids and _devices with stub entries from the persistent store."""
        for entry in self._paired_device_store.load():
            device_id = entry["device_id"]
            try:
                device_type = DeviceType(entry["device_type"])
            except ValueError:
                continue
            self._paired_ids.add(device_id)
            self._devices[device_id] = DeviceInfo(
                device_id=device_id,
                name=entry["name"],
                device_type=device_type,
                address=None,
                rssi=None,
                paired=True,
                connected=False,
                battery_percent=None,
                supports_calibration=device_type is DeviceType.POWER_METER,
            )

    def _persist_paired_ids(self) -> None:
        """Save the current set of paired device identities to the store."""
        with self._lock:
            snapshot = [
                {
                    "device_id": device.device_id,
                    "name": device.name,
                    "device_type": device.device_type.value,
                }
                for device in self._devices.values()
                if device.paired
            ]
        self._paired_device_store.save(snapshot)

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


class BleakFTMSControlTransport:
    """FTMS control transport backed by BleakDeviceBackend GATT primitives."""

    def __init__(
        self,
        backend: BleakDeviceBackend,
        device_id: str,
        *,
        subscribe_timeout_seconds: float = 3.0,
    ) -> None:
        self._backend = backend
        self._device_id = device_id
        self._subscribe_timeout_seconds = float(subscribe_timeout_seconds)
        self._indication_handler: Callable[[bytes], None] = lambda _: None
        self._subscribe_future: Future[None] | None = None
        self._lock = threading.Lock()

    def write_control_point(self, payload: bytes) -> Future[None]:
        try:
            self._ensure_subscription_ready()
        except Exception as exc:
            failed: Future[None] = Future()
            failed.set_exception(exc)
            return failed
        return self._backend.write_ftms_control_point(self._device_id, payload)

    def set_indication_handler(self, handler: Callable[[bytes], None]) -> None:
        self._indication_handler = handler
        self._ensure_subscription_ready()

    def _ensure_subscription_ready(self) -> None:
        subscription = self._ensure_subscription_started()
        subscription.result(timeout=self._subscribe_timeout_seconds)

    def _ensure_subscription_started(self) -> Future[None]:
        with self._lock:
            if self._subscribe_future is None:
                self._subscribe_future = self._backend.subscribe_ftms_control_point_indications(
                    self._device_id,
                    self._handle_indication,
                )
            return self._subscribe_future

    def _handle_indication(self, payload: bytes) -> None:
        try:
            self._indication_handler(payload)
        except Exception:
            return

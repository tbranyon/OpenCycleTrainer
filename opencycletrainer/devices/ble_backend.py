from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from concurrent.futures import Future
import contextlib
from dataclasses import replace
from functools import partial
import inspect
import logging
import sys
import threading
from typing import Any

_logger = logging.getLogger(__name__)

from .device_manager import AsyncioRunner, DeviceManager, NotificationCallback, completed_future
from .decoders.ftms import ResistanceLevelRange, decode_resistance_level_range
from .types import (
    BATTERY_LEVEL_CHARACTERISTIC_UUID,
    CONNECT_SERVICE_UUIDS,
    CPS_CONTROL_POINT_CHARACTERISTIC_UUID,
    DeviceInfo,
    DeviceType,
    FTMS_CONTROL_POINT_CHARACTERISTIC_UUID,
    FTMS_FITNESS_MACHINE_STATUS_CHARACTERISTIC_UUID,
    FTMS_RESISTANCE_LEVEL_RANGE_CHARACTERISTIC_UUID,
    NOTIFICATION_CHARACTERISTIC_UUIDS,
    infer_device_type,
)
from opencycletrainer.storage.paired_devices import PairedDeviceStore

PayloadNotificationCallback = Callable[[bytes], Awaitable[None] | None]
BatteryReader = Callable[[str], Awaitable[int | None]]

START_OFFSET_COMP_OPCODE = 0x0C

DEFAULT_CONNECT_TIMEOUT_SECONDS = 10.0
DEFAULT_AUTOCONNECT_DISCOVERY_SECONDS = 12.0
DEFAULT_RECONNECT_MAX_DELAY_SECONDS = 30.0
DEFAULT_BATTERY_POLL_SECONDS = 300.0
# BlueZ publishes a device's battery level a moment after the link comes up, so a first read
# that finds nothing is retried soon before falling back to the normal poll interval.
_BATTERY_EARLY_RETRY_SECONDS = (2.0, 10.0)
_MAX_BATTERY_PERCENT = 100
_SHUTDOWN_TIMEOUT_SECONDS = 5.0
_CALIBRATION_RESPONSE_TIMEOUT_SECONDS = 8.0

_BLUEZ_SERVICE = "org.bluez"
_BLUEZ_DEVICE_INTERFACE = "org.bluez.Device1"
_BLUEZ_BATTERY_INTERFACE = "org.bluez.Battery1"
_USE_PLATFORM_BATTERY_READER = object()


async def read_bluez_battery_percent(address: str) -> int | None:
    """Return BlueZ's battery level for *address* (Linux only), or None if it has none.

    BlueZ's battery plugin claims the standard Battery Service and hides it from GATT
    clients, exposing the level as ``org.bluez.Battery1.Percentage`` on the device instead.
    """
    from dbus_fast import BusType, Message, MessageType
    from dbus_fast.aio import MessageBus

    bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
    try:
        reply = await bus.call(
            Message(
                destination=_BLUEZ_SERVICE,
                path="/",
                interface="org.freedesktop.DBus.ObjectManager",
                member="GetManagedObjects",
            )
        )
        if reply.message_type != MessageType.METHOD_RETURN:
            return None
        for interfaces in reply.body[0].values():
            device = interfaces.get(_BLUEZ_DEVICE_INTERFACE)
            battery = interfaces.get(_BLUEZ_BATTERY_INTERFACE)
            if device is None or battery is None or "Percentage" not in battery:
                continue
            if str(device["Address"].value).upper() == address.upper():
                return int(battery["Percentage"].value)
        return None
    finally:
        bus.disconnect()


def _platform_battery_reader() -> BatteryReader | None:
    return read_bluez_battery_percent if sys.platform.startswith("linux") else None


class BleakDeviceBackend(DeviceManager):
    """Bleak-powered device manager with async scan/connect/notify plumbing.

    Every connection attempt for a device runs through a single coordinator task, so
    repeated Connect presses, autoconnect, scan-triggered reconnects and the dropout
    reconnect loop join one attempt instead of racing. Only one connect is in flight on the
    radio at a time, because BlueZ rejects overlapping LE connects with ``InProgress``.
    Devices found by discovery are connected through their discovered handle, which lets
    bleak skip the extra scan it otherwise runs inside every connect-by-address.
    """

    def __init__(
        self,
        scan_timeout_seconds: float = 5.0,
        paired_device_store: PairedDeviceStore | None = None,
        reconnect_delay_seconds: float = 3.0,
        max_reconnect_attempts: int | None = None,
        device_connection_changed_callback: Callable[[str, bool], None] | None = None,
        *,
        autoconnect_discovery_seconds: float = DEFAULT_AUTOCONNECT_DISCOVERY_SECONDS,
        connect_timeout_seconds: float = DEFAULT_CONNECT_TIMEOUT_SECONDS,
        reconnect_max_delay_seconds: float = DEFAULT_RECONNECT_MAX_DELAY_SECONDS,
        battery_poll_seconds: float = DEFAULT_BATTERY_POLL_SECONDS,
        bluez_battery_reader: BatteryReader | None | object = _USE_PLATFORM_BATTERY_READER,
    ) -> None:
        self._scan_timeout_seconds = scan_timeout_seconds
        # WARNING: omitting paired_device_store uses the real user data file. Tests MUST
        # pass PairedDeviceStore(path=tmp_path/...) or fake device entries will persist
        # to disk and reappear in the UI. This bug has bitten us three times.
        self._paired_device_store = paired_device_store if paired_device_store is not None else PairedDeviceStore()
        self._reconnect_delay_seconds = reconnect_delay_seconds
        self._max_reconnect_attempts = max_reconnect_attempts
        self._reconnect_max_delay_seconds = reconnect_max_delay_seconds
        self._autoconnect_discovery_seconds = autoconnect_discovery_seconds
        self._connect_timeout_seconds = connect_timeout_seconds
        self._battery_poll_seconds = battery_poll_seconds
        self._bluez_battery_reader: BatteryReader | None = (
            _platform_battery_reader()
            if bluez_battery_reader is _USE_PLATFORM_BATTERY_READER
            else bluez_battery_reader  # type: ignore[assignment]
        )
        self.device_connection_changed_callback = device_connection_changed_callback
        self.devices_changed_callback: Callable[[], None] | None = None
        self._runner = AsyncioRunner()
        self._lock = threading.Lock()
        self._devices: dict[str, DeviceInfo] = {}
        self._paired_ids: set[str] = set()
        self._clients: dict[str, Any] = {}
        self._subscribed_uuids: dict[str, set[str]] = {}
        self._ble_devices: dict[str, Any] = {}
        self._connecting_ids: set[str] = set()
        self._reconnecting_ids: set[str] = set()
        self._intentional_disconnects: set[str] = set()
        # The task dicts below are only touched on the asyncio loop thread.
        self._connect_tasks: dict[str, asyncio.Task[None]] = {}
        self._reconnect_tasks: dict[str, asyncio.Task[None]] = {}
        self._battery_tasks: dict[str, asyncio.Task[None]] = {}
        self._scan_task: asyncio.Task[list[DeviceInfo]] | None = None
        self._background_tasks: set[asyncio.Task[Any]] = set()
        self._connect_lock = asyncio.Lock()
        self._load_paired_ids_from_store()

    def scan(self) -> Future[list[DeviceInfo]]:
        return self._runner.submit(self._scan_once_async())

    def get_paired_devices(self) -> list[DeviceInfo]:
        with self._lock:
            paired = [self._with_activity(device) for device in self._devices.values() if device.paired]
        return sorted(paired, key=lambda device: device.name.lower())

    def get_available_devices(self) -> list[DeviceInfo]:
        with self._lock:
            available = [self._with_activity(device) for device in self._devices.values() if not device.paired]
        return sorted(available, key=lambda device: device.name.lower())

    def pair_device(self, device_id: str) -> Future[None]:
        with self._lock:
            device = self._get_device(device_id)
            self._paired_ids.add(device_id)
            self._devices[device_id] = replace(device, paired=True)
        self._persist_paired_ids()
        self._notify_devices_changed()
        return completed_future(None)

    def unpair_device(self, device_id: str) -> Future[None]:
        return self._runner.submit(self._unpair_async(device_id))

    def connect_device(self, device_id: str) -> Future[None]:
        return self._runner.submit(self._ensure_connected(device_id))

    def autoconnect_paired_devices(self) -> Future[list[str]]:
        return self._runner.submit(self._autoconnect_paired_async())

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

    def read_gatt_characteristic(self, device_id: str, characteristic_uuid: str) -> Future[bytes]:
        return self._runner.submit(
            self._read_gatt_characteristic_async(device_id, characteristic_uuid)
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

    def subscribe_fitness_machine_status(
        self,
        device_id: str,
        callback: PayloadNotificationCallback,
    ) -> Future[None]:
        return self.subscribe_characteristic(
            device_id,
            FTMS_FITNESS_MACHINE_STATUS_CHARACTERISTIC_UUID,
            callback,
        )

    def shutdown(self) -> None:
        try:
            self._runner.submit(self._disconnect_all_async()).result(timeout=_SHUTDOWN_TIMEOUT_SECONDS)
        except Exception:
            pass
        self._runner.shutdown()

    # ── Discovery ─────────────────────────────────────────────────────────────

    async def _scan_once_async(self) -> list[DeviceInfo]:
        """Run a scan, or join the one already running."""
        task = self._scan_task
        if task is None or task.done():
            task = asyncio.get_running_loop().create_task(self._scan_async())
            self._scan_task = task
        return await asyncio.shield(task)

    async def _scan_async(self) -> list[DeviceInfo]:
        seen = await self._discover(self._scan_timeout_seconds)
        with self._lock:
            reconnect_ids = [
                device_id for device_id in seen
                if device_id in self._paired_ids and device_id not in self._clients
            ]
            scanned = [self._with_activity(self._devices[device_id]) for device_id in seen if device_id in self._devices]
        for device_id in reconnect_ids:
            self._spawn(self._try_connect(device_id))
        return sorted(scanned, key=lambda device: device.name.lower())

    async def _discover(
        self,
        duration_seconds: float,
        stop_when: Callable[[set[str]], bool] | None = None,
    ) -> set[str]:
        """Listen for advertisements for up to *duration_seconds*; return the ids seen.

        Devices are recorded (and listeners notified) as each advertisement arrives, so
        results appear while the scan is still running. Stops early once *stop_when*
        returns True for the ids seen so far.
        """
        _, scanner_cls = self._load_bleak_classes()
        seen: set[str] = set()
        stop = asyncio.Event()

        def _on_detect(ble_device: Any, advertisement: Any) -> None:
            device_id = self._record_advertisement(ble_device, advertisement)
            if device_id is None:
                return
            seen.add(device_id)
            if stop_when is not None and stop_when(seen):
                stop.set()

        scanner = scanner_cls(detection_callback=_on_detect)
        await scanner.start()
        try:
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=max(0.0, duration_seconds))
        finally:
            await scanner.stop()
        return seen

    def _record_advertisement(self, ble_device: Any, advertisement: Any) -> str | None:
        """Store what an advertisement says about a device; return its id if it is relevant."""
        device_id = getattr(ble_device, "address", None) or getattr(ble_device, "name", None)
        if not device_id:
            return None
        device_type = infer_device_type(self._extract_service_uuids(ble_device, advertisement))
        rssi = getattr(advertisement, "rssi", None)
        if rssi is None:
            rssi = getattr(ble_device, "rssi", None)

        with self._lock:
            existing = self._devices.get(device_id)
            if device_type is None:
                # Some packets (e.g. scan responses on Windows) omit service UUIDs; still
                # refresh the handle for a device we already know.
                if existing is None:
                    return None
                device_type = existing.device_type
            name = getattr(ble_device, "name", None) or (existing.name if existing else "Unknown Device")
            info = DeviceInfo(
                device_id=device_id,
                name=name,
                device_type=device_type,
                address=getattr(ble_device, "address", None),
                rssi=rssi,
                paired=device_id in self._paired_ids,
                connected=device_id in self._clients,
                battery_percent=existing.battery_percent if existing else None,
                supports_calibration=(
                    existing.supports_calibration
                    if existing
                    else device_type is DeviceType.POWER_METER
                ),
            )
            changed = existing is None or (existing.name, existing.device_type, existing.address) != (
                info.name, info.device_type, info.address
            )
            self._devices[device_id] = info
            self._ble_devices[device_id] = ble_device
        if changed:
            self._notify_devices_changed()
        return device_id

    async def _autoconnect_paired_async(self) -> list[str]:
        """Connect every paired device that is not yet connected; return the ids that connected.

        Each device is connected as soon as its advertisement is seen, so devices that are
        switched off never hold up the others. Paired devices still unseen when the
        discovery window closes get one direct connect attempt by address, which reaches
        devices the OS keeps connected (those stop advertising)."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._autoconnect_discovery_seconds
        connected: list[str] = []
        attempted: set[str] = set()
        while True:
            pending = self._unconnected_paired_ids() - attempted
            remaining = deadline - loop.time()
            if not pending or remaining <= 0:
                break
            try:
                seen = await self._discover(remaining, stop_when=lambda ids, wanted=pending: bool(ids & wanted))
            except Exception as exc:
                _logger.warning("Autoconnect discovery failed: %s", exc)
                break
            ready = sorted(seen & pending)
            if not ready:
                break
            for device_id in ready:
                attempted.add(device_id)
                if await self._try_connect(device_id):
                    connected.append(device_id)

        for device_id in sorted(self._unconnected_paired_ids() - attempted):
            if await self._try_connect(device_id):
                connected.append(device_id)
        return connected

    def _unconnected_paired_ids(self) -> set[str]:
        with self._lock:
            return {device_id for device_id in self._paired_ids if device_id not in self._clients}

    # ── Connection lifecycle ──────────────────────────────────────────────────

    async def _try_connect(self, device_id: str) -> bool:
        """Connect *device_id*, logging rather than raising on failure; return success."""
        try:
            await self._ensure_connected(device_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _logger.warning("Could not connect to paired device '%s': %s", device_id, exc)
            return False
        return True

    async def _ensure_connected(self, device_id: str) -> None:
        """Connect *device_id*, joining the attempt already in progress if there is one."""
        with self._lock:
            self._get_device(device_id)
            client = self._clients.get(device_id)
        if client is not None and getattr(client, "is_connected", False):
            return
        task = self._connect_tasks.get(device_id)
        if task is None:
            task = asyncio.get_running_loop().create_task(self._connect_once(device_id))
            self._connect_tasks[device_id] = task
            with self._lock:
                self._connecting_ids.add(device_id)
            task.add_done_callback(partial(self._on_connect_task_done, device_id))
            self._notify_devices_changed()
        await asyncio.shield(task)

    def _on_connect_task_done(self, device_id: str, task: asyncio.Task[None]) -> None:
        if self._connect_tasks.get(device_id) is task:
            del self._connect_tasks[device_id]
            with self._lock:
                self._connecting_ids.discard(device_id)
        if not task.cancelled() and task.exception() is not None:
            _logger.info("Connect attempt for '%s' failed: %r", device_id, task.exception())
        self._notify_devices_changed()

    async def _connect_once(self, device_id: str) -> None:
        client_cls, _ = self._load_bleak_classes()
        with self._lock:
            device = self._get_device(device_id)
            ble_device = self._ble_devices.get(device_id)
            self._intentional_disconnects.discard(device_id)
        target = ble_device if ble_device is not None else (device.address or device.device_id)
        client_ref: dict[str, Any] = {}

        def _on_disconnect(_: Any) -> None:
            self._handle_disconnect(device_id, client_ref.get("client"))

        async with self._connect_lock:
            client = client_cls(
                target,
                disconnected_callback=_on_disconnect,
                timeout=self._connect_timeout_seconds,
                services=list(CONNECT_SERVICE_UUIDS),
            )
            client_ref["client"] = client
            try:
                await client.connect()
            except asyncio.CancelledError:
                with contextlib.suppress(Exception):
                    await client.disconnect()
                raise
            except Exception:
                if ble_device is not None:
                    # The discovered handle may be stale; the next attempt goes by address.
                    with self._lock:
                        if self._ble_devices.get(device_id) is ble_device:
                            del self._ble_devices[device_id]
                raise

        with self._lock:
            refreshed = self._get_device(device_id)
            self._clients[device_id] = client
            self._devices[device_id] = replace(refreshed, connected=True)
            self._connecting_ids.discard(device_id)
            self._reconnecting_ids.discard(device_id)
        self._start_battery_monitor(device_id, client)
        self._notify_devices_changed()

    def _handle_disconnect(self, device_id: str, client: Any) -> None:
        """React to bleak reporting that *client*'s link dropped (may run on any thread)."""
        with self._lock:
            if client is not None and self._clients.get(device_id) is not client:
                return
            intentional = device_id in self._intentional_disconnects
            self._intentional_disconnects.discard(device_id)
            self._clients.pop(device_id, None)
            self._subscribed_uuids.pop(device_id, None)
            if device_id in self._devices:
                self._devices[device_id] = replace(self._devices[device_id], connected=False)
            still_paired = device_id in self._paired_ids
        _logger.info("Device '%s' disconnected (intentional=%s)", device_id, intentional)
        self._fire_connection_changed(device_id, False)
        self._submit_quietly(self._cancel_battery_monitor_async(device_id))
        if not intentional and still_paired:
            self._submit_quietly(self._reconnect_loop_async(device_id))
        self._notify_devices_changed()

    def _submit_quietly(self, coroutine: Awaitable[Any]) -> None:
        """Schedule *coroutine* on the BLE loop from any thread; drop it after shutdown."""
        try:
            self._runner.submit(coroutine)
        except RuntimeError:
            close = getattr(coroutine, "close", None)
            if close is not None:
                close()

    def _spawn(self, coroutine: Awaitable[Any]) -> None:
        """Start a fire-and-forget task on the running loop, keeping it referenced until done."""
        task = asyncio.get_running_loop().create_task(coroutine)
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    async def _unpair_async(self, device_id: str) -> None:
        await self._disconnect_async(device_id)
        with self._lock:
            device = self._get_device(device_id)
            self._paired_ids.discard(device_id)
            self._devices[device_id] = replace(device, paired=False, connected=False)
        self._persist_paired_ids()
        self._notify_devices_changed()

    async def _disconnect_async(self, device_id: str) -> None:
        """Disconnect *device_id*, cancelling any connect or reconnect still in progress."""
        with self._lock:
            client = self._clients.get(device_id)
            uuids_to_unsub = list(self._subscribed_uuids.pop(device_id, set()))
            self._intentional_disconnects.add(device_id)
        await self._cancel_task(self._reconnect_tasks.pop(device_id, None))
        await self._cancel_task(self._connect_tasks.get(device_id))
        await self._cancel_battery_monitor_async(device_id)
        if client is not None:
            for uuid in uuids_to_unsub:
                try:
                    await client.stop_notify(uuid)
                except Exception:
                    pass
            await client.disconnect()
        with self._lock:
            self._clients.pop(device_id, None)
            self._connecting_ids.discard(device_id)
            self._reconnecting_ids.discard(device_id)
            device = self._get_device(device_id)
            self._devices[device_id] = replace(device, connected=False)
        self._notify_devices_changed()

    async def _disconnect_all_async(self) -> None:
        with self._lock:
            device_ids = set(self._clients) | self._connecting_ids | self._reconnecting_ids
        for device_id in device_ids:
            with contextlib.suppress(Exception):
                await self._disconnect_async(device_id)
        await self._cancel_task(self._scan_task)
        for task in list(self._background_tasks):
            await self._cancel_task(task)

    async def _reconnect_loop_async(self, device_id: str) -> None:
        """Keep reconnecting a paired device that dropped unexpectedly, with backoff.

        Stops when the device reconnects, is unpaired or disconnected on purpose, or the
        optional attempt limit is reached. With no limit it keeps trying, so a sensor that
        comes back minutes later (fresh battery, rider returns) reconnects by itself.
        """
        with self._lock:
            if device_id in self._reconnecting_ids:
                return
            self._reconnecting_ids.add(device_id)
        current = asyncio.current_task()
        if current is not None:
            self._reconnect_tasks[device_id] = current
        self._notify_devices_changed()
        attempt = 0
        try:
            while self._max_reconnect_attempts is None or attempt < self._max_reconnect_attempts:
                delay = min(
                    self._reconnect_delay_seconds * (2 ** attempt),
                    max(self._reconnect_delay_seconds, self._reconnect_max_delay_seconds),
                )
                attempt += 1
                await asyncio.sleep(delay)
                with self._lock:
                    still_paired = device_id in self._paired_ids
                    already_connected = device_id in self._clients
                if not still_paired or already_connected:
                    return
                try:
                    await self._ensure_connected(device_id)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    _logger.warning("Reconnect attempt %d failed for '%s': %s", attempt, device_id, exc)
                    continue
                _logger.info("Device '%s' reconnected successfully", device_id)
                self._fire_connection_changed(device_id, True)
                return
        finally:
            # A newer loop may have started once the connect cleared the flag; leave its flag alone.
            if self._reconnect_tasks.get(device_id) is current:
                del self._reconnect_tasks[device_id]
                with self._lock:
                    self._reconnecting_ids.discard(device_id)
            self._notify_devices_changed()

    @staticmethod
    async def _cancel_task(task: asyncio.Task[Any] | None) -> None:
        if task is None or task.done() or task is asyncio.current_task():
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task

    # ── Battery ───────────────────────────────────────────────────────────────

    def _start_battery_monitor(self, device_id: str, client: Any) -> None:
        previous = self._battery_tasks.pop(device_id, None)
        if previous is not None:
            previous.cancel()
        self._battery_tasks[device_id] = asyncio.get_running_loop().create_task(
            self._battery_monitor_async(device_id, client)
        )

    async def _cancel_battery_monitor_async(self, device_id: str) -> None:
        await self._cancel_task(self._battery_tasks.pop(device_id, None))

    async def _battery_monitor_async(self, device_id: str, client: Any) -> None:
        """Read the battery level now and then periodically while *client* stays connected."""
        early_retries = iter(_BATTERY_EARLY_RETRY_SECONDS)
        while getattr(client, "is_connected", False):
            percent = await self._read_battery_percent(device_id, client)
            if percent is not None:
                self._set_battery_percent(device_id, percent)
                delay = self._battery_poll_seconds
            else:
                delay = next(early_retries, self._battery_poll_seconds)
            await asyncio.sleep(delay)

    async def _read_battery_percent(self, device_id: str, client: Any) -> int | None:
        """Read the standard Battery Level characteristic, falling back to BlueZ's copy."""
        try:
            payload = await client.read_gatt_char(BATTERY_LEVEL_CHARACTERISTIC_UUID)
            if payload:
                return min(int(payload[0]), _MAX_BATTERY_PERCENT)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _logger.debug("No GATT battery level for '%s': %s", device_id, exc)
        reader = self._bluez_battery_reader
        if reader is None:
            return None
        with self._lock:
            device = self._devices.get(device_id)
        address = (device.address if device is not None else None) or device_id
        try:
            percent = await reader(address)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _logger.debug("No BlueZ battery level for '%s': %s", device_id, exc)
            return None
        return min(int(percent), _MAX_BATTERY_PERCENT) if percent is not None else None

    def _set_battery_percent(self, device_id: str, percent: int) -> None:
        with self._lock:
            device = self._devices.get(device_id)
            if device is None or device.battery_percent == percent:
                return
            self._devices[device_id] = replace(device, battery_percent=percent)
        self._notify_devices_changed()

    # ── Notifications to listeners ────────────────────────────────────────────

    def _with_activity(self, device: DeviceInfo) -> DeviceInfo:
        """Return *device* with its in-progress flags filled in (caller holds the lock)."""
        connecting = device.device_id in self._connecting_ids
        reconnecting = device.device_id in self._reconnecting_ids
        if not connecting and not reconnecting:
            return device
        return replace(device, connecting=connecting, reconnecting=reconnecting)

    def _notify_devices_changed(self) -> None:
        callback = self.devices_changed_callback
        if callback is None:
            return
        try:
            callback()
        except Exception:
            _logger.exception("devices_changed_callback raised")

    def _fire_connection_changed(self, device_id: str, connected: bool) -> None:
        callback = self.device_connection_changed_callback
        if callback is None:
            return
        try:
            callback(device_id, connected)
        except Exception:
            _logger.exception("device_connection_changed_callback raised")

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
            except Exception as exc:
                _logger.warning("Failed to subscribe to CPS control point on device '%s': %s", device_id, exc)

            # Cycling Power Control Point opcode 0x0C = Start Offset Compensation (zero-offset)
            await client.write_gatt_char(
                CPS_CONTROL_POINT_CHARACTERISTIC_UUID,
                bytearray([START_OFFSET_COMP_OPCODE]),
                response=True,
            )

            if indication_subscribed:
                try:
                    await asyncio.wait_for(indication_event.wait(), timeout=_CALIBRATION_RESPONSE_TIMEOUT_SECONDS)
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
                except Exception as exc:
                    _logger.debug("Failed to unsubscribe from CPS control point on device '%s': %s", device_id, exc)

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
                with self._lock:
                    self._subscribed_uuids.setdefault(device_id, set()).add(characteristic_uuid)
            except Exception as exc:
                _logger.warning(
                    "Failed to subscribe to characteristic %s for device '%s': %s",
                    characteristic_uuid,
                    device_id,
                    exc,
                )
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

    async def _read_gatt_characteristic_async(self, device_id: str, characteristic_uuid: str) -> bytes:
        with self._lock:
            client = self._clients.get(device_id)
        if client is None or not getattr(client, "is_connected", False):
            raise RuntimeError(f"Device {device_id} is not connected")
        return bytes(await client.read_gatt_char(characteristic_uuid))

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
        with self._lock:
            self._subscribed_uuids.setdefault(device_id, set()).add(characteristic_uuid)

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
        self._resistance_range_cache: ResistanceLevelRange | None = None
        self._resistance_range_cache_loaded: bool = False
        self._status_handler: Callable[[bytes], None] = lambda _: None
        self._status_subscribe_future: Future[None] | None = None

    def write_control_point(self, payload: bytes) -> Future[None]:
        try:
            self._ensure_subscription_ready()
        except Exception as exc:
            failed: Future[None] = Future()
            failed.set_exception(exc)
            return failed
        return self._backend.write_ftms_control_point(self._device_id, payload)

    def read_resistance_level_range(self) -> ResistanceLevelRange | None:
        """Read and decode Supported Resistance Level Range (0x2AD6), cached after first read.

        Returns None on any failure (characteristic not present, malformed payload, etc.).
        """
        if self._resistance_range_cache_loaded:
            return self._resistance_range_cache
        try:
            payload = self._backend.read_gatt_characteristic(
                self._device_id,
                FTMS_RESISTANCE_LEVEL_RANGE_CHARACTERISTIC_UUID,
            ).result(timeout=self._subscribe_timeout_seconds)
            self._resistance_range_cache = decode_resistance_level_range(payload)
        except Exception as exc:
            _logger.warning(
                "Failed to read resistance level range for '%s': %s", self._device_id, exc
            )
            self._resistance_range_cache = None
        self._resistance_range_cache_loaded = True
        return self._resistance_range_cache

    def set_indication_handler(self, handler: Callable[[bytes], None]) -> None:
        self._indication_handler = handler
        self._ensure_subscription_ready()

    def subscribe_status(self, handler: Callable[[bytes], None]) -> None:
        self._status_handler = handler
        self._ensure_status_subscription_started().result(timeout=self._subscribe_timeout_seconds)

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

    def _ensure_status_subscription_started(self) -> Future[None]:
        with self._lock:
            if self._status_subscribe_future is None:
                self._status_subscribe_future = self._backend.subscribe_fitness_machine_status(
                    self._device_id,
                    self._handle_status,
                )
            return self._status_subscribe_future

    def _handle_indication(self, payload: bytes) -> None:
        try:
            self._indication_handler(payload)
        except Exception:
            return

    def _handle_status(self, payload: bytes) -> None:
        try:
            self._status_handler(payload)
        except Exception:
            return

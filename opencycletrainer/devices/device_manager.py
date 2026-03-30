from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from concurrent.futures import Future
import threading
from typing import TypeVar

from .types import DeviceInfo

T = TypeVar("T")
NotificationCallback = Callable[[str, str, bytes], Awaitable[None] | None]


def completed_future(value: T) -> Future[T]:
    future: Future[T] = Future()
    future.set_result(value)
    return future


class AsyncioRunner:
    """Runs an asyncio event loop in a dedicated background thread."""

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="bleak-loop")
        self._ready = threading.Event()
        self._closed = False
        self._thread.start()
        self._ready.wait()

    def _run_loop(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        self._ready.set()
        loop.run_forever()
        pending = asyncio.all_tasks(loop)
        for task in pending:
            task.cancel()
        if pending:
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        loop.close()

    def submit(self, coroutine: Awaitable[T]) -> Future[T]:
        with self._lock:
            if self._closed or self._loop is None:
                raise RuntimeError("AsyncioRunner is closed")
            loop = self._loop
        return asyncio.run_coroutine_threadsafe(coroutine, loop)

    def shutdown(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            loop = self._loop
        if loop is not None:
            loop.call_soon_threadsafe(loop.stop)
        self._thread.join(timeout=2.0)


class DeviceManager(ABC):
    @abstractmethod
    def scan(self) -> Future[list[DeviceInfo]]:
        """Scan and return relevant devices."""

    @abstractmethod
    def get_paired_devices(self) -> list[DeviceInfo]:
        """Return currently paired devices."""

    @abstractmethod
    def get_available_devices(self) -> list[DeviceInfo]:
        """Return currently available unpaired devices."""

    @abstractmethod
    def pair_device(self, device_id: str) -> Future[None]:
        """Pair a device."""

    @abstractmethod
    def unpair_device(self, device_id: str) -> Future[None]:
        """Unpair a device."""

    @abstractmethod
    def connect_device(self, device_id: str) -> Future[None]:
        """Connect to a device."""

    @abstractmethod
    def disconnect_device(self, device_id: str) -> Future[None]:
        """Disconnect from a device."""

    @abstractmethod
    def calibrate_device(self, device_id: str) -> Future[int | None]:
        """Send zero-offset calibration command; returns offset value if received, None if sent
        but no offset in response. Raises if the device does not support calibration."""

    @abstractmethod
    def subscribe_device_notifications(
        self,
        device_id: str,
        callback: NotificationCallback,
    ) -> Future[None]:
        """Subscribe to notifications for the given device."""

    @abstractmethod
    def read_gatt_characteristic(self, device_id: str, characteristic_uuid: str) -> Future[bytes]:
        """Read a GATT characteristic from a connected device."""

    def shutdown(self) -> None:
        """Optional lifecycle hook for backend cleanup."""

"""Shared OS-keyring helpers for the integration credential stores.

Each keyring call can be a slow round trip (D-Bus to the Secret Service on Linux), and the
stores used to probe the keyring before every read. Reads now go straight to the keyring
and fall back to the file store on any error; writes still need to know whether the
keyring works, and that probe result is remembered for the current backend.
"""

from __future__ import annotations

import threading

import keyring

_PROBE_SERVICE = "OpenCycleTrainer"
_PROBE_USERNAME = "__probe__"

_probe_lock = threading.Lock()
_probed_backend: object | None = None
_probed_result = False


def keyring_is_usable() -> bool:
    """Return True if the active keyring backend works, probing it once per backend."""
    global _probed_backend, _probed_result
    backend = keyring.get_keyring()
    with _probe_lock:
        if backend is _probed_backend:
            return _probed_result
    try:
        backend.get_password(_PROBE_SERVICE, _PROBE_USERNAME)
        usable = True
    except Exception:
        usable = False
    with _probe_lock:
        _probed_backend = backend
        _probed_result = usable
    return usable


def read_secret(service: str, username: str) -> str | None:
    """Return the stored secret, or None when it is absent or the keyring is unusable."""
    try:
        return keyring.get_password(service, username)
    except Exception:
        return None

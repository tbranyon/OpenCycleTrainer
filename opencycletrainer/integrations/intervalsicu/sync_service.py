from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from .key_store import get_api_key
from .upload_history import is_already_uploaded, record_upload

_logger = logging.getLogger(__name__)
_MAX_ATTEMPTS = 3
_API_BASE = "https://intervals.icu/api/v1"
# intervals.icu resolves athlete id "0" to the owner of the supplied API key.
_SELF_ATHLETE_ID = "0"
# HTTP Basic auth uses a literal username with the key as the password.
_BASIC_AUTH_USERNAME = "API_KEY"
_REQUEST_TIMEOUT_SECONDS = 60


class DuplicateUploadError(Exception):
    """Raised when a FIT file has already been successfully uploaded to intervals.icu."""


def upload_fit_to_intervals_icu(
    fit_path: Path,
    activity_name: str | None = None,
    *,
    _key_getter: Callable[[], str | None] | None = None,
    _upload_impl: Callable[[Path, str, str | None], None] | None = None,
    _history_checker: Callable[[Path], bool] | None = None,
    _history_recorder: Callable[[Path], None] | None = None,
) -> None:
    """Upload a FIT file to intervals.icu with duplicate detection and bounded retries.

    Raises:
        DuplicateUploadError: if this file has already been successfully uploaded.
        RuntimeError: if no API key is configured or all upload attempts fail.

    The leading-underscore parameters are injection points for testing only.
    """
    key_getter = _key_getter if _key_getter is not None else get_api_key
    upload_fn = _upload_impl if _upload_impl is not None else _do_upload
    history_checker = _history_checker if _history_checker is not None else is_already_uploaded
    history_recorder = _history_recorder if _history_recorder is not None else record_upload

    if history_checker(fit_path):
        _logger.info("Skipping duplicate intervals.icu upload for %s", fit_path.name)
        raise DuplicateUploadError(f"{fit_path.name} has already been uploaded to intervals.icu")

    api_key = key_getter()
    if not api_key:
        raise RuntimeError("No intervals.icu API key configured")

    _logger.info("Starting intervals.icu upload for %s", fit_path.name)
    last_exc: Exception | None = None
    for attempt in range(_MAX_ATTEMPTS):
        try:
            upload_fn(fit_path, api_key, activity_name)
            history_recorder(fit_path)
            _logger.info("intervals.icu upload succeeded for %s", fit_path.name)
            break
        except DuplicateUploadError:
            raise
        except Exception as exc:  # noqa: BLE001
            _logger.warning(
                "intervals.icu upload attempt %d/%d failed: %s",
                attempt + 1,
                _MAX_ATTEMPTS,
                exc,
            )
            last_exc = exc
    else:
        raise RuntimeError(
            f"intervals.icu upload failed after {_MAX_ATTEMPTS} attempts"
        ) from last_exc


def validate_api_key(api_key: str) -> str:
    """Validate an API key against intervals.icu and return the athlete's display name.

    Raises RuntimeError if the key is invalid or the request fails.
    """
    import requests  # noqa: PLC0415

    resp = requests.get(
        f"{_API_BASE}/athlete/{_SELF_ATHLETE_ID}/profile",
        auth=(_BASIC_AUTH_USERNAME, api_key),
        timeout=_REQUEST_TIMEOUT_SECONDS,
    )
    if resp.status_code in (401, 403):
        raise RuntimeError("intervals.icu rejected the API key")
    resp.raise_for_status()
    data = resp.json()
    athlete = data.get("athlete", data) if isinstance(data, dict) else {}
    return str(athlete.get("name", "")) if isinstance(athlete, dict) else ""


def _do_upload(fit_path: Path, api_key: str, activity_name: str | None = None) -> None:
    """Upload a FIT file to intervals.icu using a multipart POST."""
    import requests  # noqa: PLC0415

    try:
        file_size = fit_path.stat().st_size
    except OSError:
        file_size = 0
    external_id = f"{fit_path.name}_{file_size}"
    params = {
        "name": activity_name or fit_path.stem,
        "external_id": external_id,
    }

    with fit_path.open("rb") as f:
        resp = requests.post(
            f"{_API_BASE}/athlete/{_SELF_ATHLETE_ID}/activities",
            auth=(_BASIC_AUTH_USERNAME, api_key),
            params=params,
            files={"file": (fit_path.name, f, "application/octet-stream")},
            timeout=_REQUEST_TIMEOUT_SECONDS,
        )

    if _is_duplicate_response(resp):
        raise DuplicateUploadError("intervals.icu reported a duplicate activity")
    resp.raise_for_status()


def _is_duplicate_response(resp: object) -> bool:
    """Return True if the response indicates the activity already exists."""
    status = getattr(resp, "status_code", None)
    if status == 409:
        return True
    text = getattr(resp, "text", "") or ""
    return "duplicate" in text.lower()

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from pathlib import Path

from .token_store import StravaTokenBundle, get_tokens, save_tokens
from .upload_history import is_already_uploaded, record_upload

_logger = logging.getLogger(__name__)
_MAX_ATTEMPTS = 3
# Seconds to wait before each successive upload status poll.
# First check is after 5 s; subsequent delays double until capped at 60 s.
_POLL_SCHEDULE = [5, 10, 20, 40, 60, 60, 60]


class DuplicateUploadError(Exception):
    """Raised when a FIT file has already been successfully uploaded to Strava."""


def upload_fit_to_strava(
    fit_path: Path,
    chart_image_path: Path | None = None,
    *,
    _token_getter: Callable[[], StravaTokenBundle | None] | None = None,
    _token_saver: Callable[[StravaTokenBundle], None] | None = None,
    _upload_impl: Callable[[Path, str], str | None] | None = None,
    _refresh_impl: Callable[[StravaTokenBundle], StravaTokenBundle] | None = None,
    _history_checker: Callable[[Path], bool] | None = None,
    _history_recorder: Callable[[Path], None] | None = None,
    _image_uploader: Callable[[str, Path, str], None] | None = None,
) -> None:
    """Upload a FIT file to Strava with duplicate detection, token refresh, and bounded retries.

    If chart_image_path is provided and the FIT upload returns an activity ID, the image
    is attached to the activity on a best-effort basis.

    Raises:
        DuplicateUploadError: if this file has already been successfully uploaded.
        RuntimeError: if tokens are unavailable or all upload attempts fail.

    The leading-underscore parameters are injection points for testing only.
    """
    token_getter = _token_getter if _token_getter is not None else get_tokens
    token_saver = _token_saver if _token_saver is not None else save_tokens
    upload_fn = _upload_impl if _upload_impl is not None else _do_upload
    refresh_fn = _refresh_impl if _refresh_impl is not None else _refresh_tokens
    history_checker = _history_checker if _history_checker is not None else is_already_uploaded
    history_recorder = _history_recorder if _history_recorder is not None else record_upload
    image_uploader = _image_uploader if _image_uploader is not None else _do_image_upload

    if history_checker(fit_path):
        _logger.info("Skipping duplicate Strava upload for %s", fit_path.name)
        raise DuplicateUploadError(f"{fit_path.name} has already been uploaded to Strava")

    tokens = token_getter()
    if tokens is None:
        raise RuntimeError("No Strava tokens available")

    if time.time() >= tokens.expires_at:
        _logger.debug("Refreshing expired Strava access token")
        tokens = refresh_fn(tokens)
        token_saver(tokens)

    _logger.info("Starting Strava upload for %s", fit_path.name)
    last_exc: Exception | None = None
    activity_id: str | None = None
    for attempt in range(_MAX_ATTEMPTS):
        try:
            activity_id = upload_fn(fit_path, tokens.access_token)
            history_recorder(fit_path)
            _logger.info("Strava upload succeeded for %s", fit_path.name)
            break
        except Exception as exc:  # noqa: BLE001
            _logger.warning(
                "Strava upload attempt %d/%d failed: %s",
                attempt + 1,
                _MAX_ATTEMPTS,
                exc,
            )
            last_exc = exc
    else:
        raise RuntimeError(
            f"Strava upload failed after {_MAX_ATTEMPTS} attempts"
        ) from last_exc

    if chart_image_path and activity_id:
        _try_upload_chart_image(
            activity_id=activity_id,
            chart_image_path=chart_image_path,
            access_token=tokens.access_token,
            image_uploader=image_uploader,
        )


def _try_upload_chart_image(
    *,
    activity_id: str,
    chart_image_path: Path,
    access_token: str,
    image_uploader: Callable[[str, Path, str], None],
) -> None:
    """Upload a chart image to the activity, best-effort."""
    try:
        image_uploader(activity_id, chart_image_path, access_token)
        _logger.info("Chart image uploaded to Strava activity %s", activity_id)
    except Exception as exc:  # noqa: BLE001
        _logger.warning("Strava chart image upload failed (non-blocking): %s", exc)


def _refresh_tokens(tokens: StravaTokenBundle) -> StravaTokenBundle:
    """Refresh an expired Strava token bundle using the app credentials."""
    from stravalib import Client  # noqa: PLC0415

    from .app_credentials import load_app_credentials  # noqa: PLC0415

    creds = load_app_credentials()
    client = Client()
    resp = client.refresh_access_token(
        client_id=creds.client_id,
        client_secret=creds.client_secret,
        refresh_token=tokens.refresh_token,
    )
    return StravaTokenBundle(
        access_token=str(resp["access_token"]),
        refresh_token=str(resp["refresh_token"]),
        expires_at=int(resp["expires_at"]),
    )


def _do_upload(fit_path: Path, access_token: str) -> str | None:
    """Upload a FIT file to Strava using stravalib. Returns the activity ID or None."""
    from stravalib import Client  # noqa: PLC0415

    try:
        file_size = fit_path.stat().st_size
    except OSError:
        file_size = 0
    external_id = f"{fit_path.name}_{file_size}"

    client = Client(access_token=access_token)
    with fit_path.open("rb") as f:
        uploader = client.upload_activity(
            activity_file=f,
            data_type="fit",
            name=fit_path.stem,
            external_id=external_id,
        )
    try:
        for delay in _POLL_SCHEDULE:
            time.sleep(delay)
            uploader.poll()
            if uploader.activity_id is not None:
                return str(uploader.activity_id)
        raise RuntimeError("Strava upload timed out waiting for server processing")
    except Exception as exc:  # noqa: BLE001
        if "duplicate" in str(exc).lower():
            raise DuplicateUploadError("Strava reported a duplicate activity") from exc
        raise


def _do_image_upload(activity_id: str, image_path: Path, access_token: str) -> None:
    """Upload a chart image to the Strava activity photo gallery."""
    import requests  # noqa: PLC0415

    url = f"https://www.strava.com/api/v3/activities/{activity_id}/photos"
    with image_path.open("rb") as f:
        resp = requests.post(
            url,
            headers={"Authorization": f"Bearer {access_token}"},
            files={"file": (image_path.name, f, "image/png")},
            data={"caption": "Workout Power Chart"},
            timeout=30,
        )
    resp.raise_for_status()

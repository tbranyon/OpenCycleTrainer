"""Keeps the app's FTP and intervals.icu's FTP in step, always asking the rider first."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
import logging

from PySide6.QtCore import QObject, Signal

from opencycletrainer.integrations.intervalsicu.ftp_service import RemoteFtp, fetch_ftp, push_ftp

_logger = logging.getLogger(__name__)

_PULL_TITLE = "Use FTP from intervals.icu?"
_PUSH_TITLE = "Update FTP on intervals.icu?"


class IntervalsIcuFtpSync(QObject):
    """Offers to pull FTP from intervals.icu at startup and to push local edits back.

    Network calls run off the UI thread; their results come back through signals, so
    every prompt and settings change happens on the UI thread. Nothing is changed on
    either side without a yes from the rider.
    """

    _startup_fetched = Signal(object)        # RemoteFtp | None | Exception
    _edit_fetched = Signal(int, object)      # edited watts, RemoteFtp | None | Exception
    _pushed = Signal(int, object)            # pushed watts, None | Exception

    def __init__(
        self,
        *,
        api_key_getter: Callable[[], str | None],
        local_ftp_getter: Callable[[], int],
        apply_local_ftp: Callable[[int], None],
        confirm: Callable[[str, str], bool],
        notify: Callable[[str], None],
        declined_ftp_getter: Callable[[], int | None],
        remember_declined_ftp: Callable[[int | None], None],
        fetch_fn: Callable[[str], RemoteFtp | None] = fetch_ftp,
        push_fn: Callable[[str, RemoteFtp, int], None] = push_ftp,
        run_async: Callable[[Callable[[], None]], None] | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._api_key_getter = api_key_getter
        self._local_ftp_getter = local_ftp_getter
        self._apply_local_ftp = apply_local_ftp
        self._confirm = confirm
        self._notify = notify
        self._declined_ftp_getter = declined_ftp_getter
        self._remember_declined_ftp = remember_declined_ftp
        self._fetch_fn = fetch_fn
        self._push_fn = push_fn
        self._executor: ThreadPoolExecutor | None = None
        self._run_async = run_async if run_async is not None else self._submit
        # The last FTP already dealt with, so re-announcing it (Enter, then the field
        # losing focus) or applying a pulled value does not ask the rider twice.
        self._settled_ftp = int(local_ftp_getter())

        self._startup_fetched.connect(self._on_startup_fetched)
        self._edit_fetched.connect(self._on_edit_fetched)
        self._pushed.connect(self._on_pushed)

    # ── Public API ────────────────────────────────────────────────────────────

    def check_on_startup(self) -> None:
        """Compare FTP with intervals.icu and offer to adopt its value if they differ."""
        api_key = self._api_key_getter()
        if not api_key:
            return
        self._run_async(lambda: self._startup_fetched.emit(self._fetch(api_key)))

    def on_local_ftp_edited(self, watts: int) -> None:
        """Offer to send a newly entered FTP to intervals.icu if it holds another value."""
        watts = int(watts)
        if watts == self._settled_ftp:
            return
        api_key = self._api_key_getter()
        if not api_key:
            return
        self._settled_ftp = watts
        self._run_async(lambda: self._edit_fetched.emit(watts, self._fetch(api_key)))

    def shutdown(self) -> None:
        """Stop accepting background work; requests in flight are abandoned."""
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=True)
            self._executor = None

    # ── Result handlers (UI thread) ───────────────────────────────────────────

    def _on_startup_fetched(self, remote: object) -> None:
        if not isinstance(remote, RemoteFtp):
            return
        local = int(self._local_ftp_getter())
        if remote.watts == local or remote.watts == self._declined_ftp_getter():
            return
        text = (
            f"intervals.icu has your {_describe(remote)} as {remote.watts} W.\n"
            f"OpenCycleTrainer is set to {local} W.\n\n"
            f"Use {remote.watts} W in OpenCycleTrainer?"
        )
        if self._confirm(_PULL_TITLE, text):
            self._settled_ftp = remote.watts
            self._apply_local_ftp(remote.watts)
        else:
            self._remember_declined_ftp(remote.watts)

    def _on_edit_fetched(self, watts: int, remote: object) -> None:
        if not isinstance(remote, RemoteFtp) or remote.watts == watts:
            return
        if int(self._local_ftp_getter()) != watts:
            return  # edited again while intervals.icu was being asked
        api_key = self._api_key_getter()
        if not api_key:
            return
        text = (
            f"intervals.icu has your {_describe(remote)} as {remote.watts} W.\n\n"
            f"Update it to {watts} W?"
        )
        if self._confirm(_PUSH_TITLE, text):
            self._run_async(lambda: self._pushed.emit(watts, self._push(api_key, remote, watts)))

    def _on_pushed(self, watts: int, error: object) -> None:
        if isinstance(error, Exception):
            self._notify(f"Couldn't update FTP on intervals.icu: {error}")
        else:
            self._notify(f"intervals.icu FTP updated to {watts} W")

    # ── Background jobs ───────────────────────────────────────────────────────

    def _fetch(self, api_key: str) -> RemoteFtp | None | Exception:
        try:
            return self._fetch_fn(api_key)
        except Exception as exc:  # noqa: BLE001
            _logger.warning("Could not read FTP from intervals.icu: %s", exc)
            return exc

    def _push(self, api_key: str, remote: RemoteFtp, watts: int) -> Exception | None:
        try:
            self._push_fn(api_key, remote, watts)
        except Exception as exc:  # noqa: BLE001
            _logger.warning("Could not update FTP on intervals.icu: %s", exc)
            return exc
        return None

    def _submit(self, job: Callable[[], None]) -> None:
        if self._executor is None:
            self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="intervals-icu-ftp")
        self._executor.submit(job)


def _describe(remote: RemoteFtp) -> str:
    return "indoor FTP" if remote.indoor else "FTP"

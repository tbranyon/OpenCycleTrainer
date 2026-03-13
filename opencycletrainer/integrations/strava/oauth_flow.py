from __future__ import annotations

import http.server
import secrets
import socket
import threading
import webbrowser
from dataclasses import dataclass
from urllib.parse import parse_qs, urlencode, urlunparse

import logging

from .app_credentials import StravaAppCredentials
from .token_store import StravaTokenBundle

_logger = logging.getLogger(__name__)
_STRAVA_AUTHORIZE_BASE = "https://www.strava.com/oauth/authorize"
_STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"
_DEFAULT_TIMEOUT_SECONDS = 120.0


@dataclass(frozen=True)
class OAuthResult:
    """Result of a completed Strava OAuth flow."""

    token_bundle: StravaTokenBundle
    athlete_name: str


def generate_state() -> str:
    """Return a cryptographically random URL-safe state token."""
    return secrets.token_urlsafe(32)


def build_auth_url(credentials: StravaAppCredentials, redirect_uri: str, state: str) -> str:
    """Return the Strava authorization URL for the given credentials and redirect."""
    params = {
        "client_id": credentials.client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "approval_prompt": "auto",
        "scope": "read,activity:write",
        "state": state,
    }
    return f"{_STRAVA_AUTHORIZE_BASE}?{urlencode(params)}"


def parse_callback(query_string: str) -> tuple[str, str]:
    """Parse ``code`` and ``state`` from an OAuth callback query string.

    Args:
        query_string: URL query string, with or without a leading ``?``.

    Returns:
        Tuple of ``(code, state)``.

    Raises:
        ValueError: if ``code`` or ``state`` is missing.
    """
    qs = query_string.lstrip("?")
    if not qs:
        raise ValueError("OAuth callback query string is empty")
    params = parse_qs(qs)

    code_list = params.get("code", [])
    state_list = params.get("state", [])

    if not code_list:
        raise ValueError("OAuth callback missing 'code' parameter")
    if not state_list:
        raise ValueError("OAuth callback missing 'state' parameter")

    return code_list[0], state_list[0]


def validate_state(expected: str, received: str) -> None:
    """Raise ValueError on OAuth state mismatch."""
    if received != expected:
        raise ValueError(f"OAuth state mismatch: expected {expected!r}, got {received!r}")


# ── loopback callback server ──────────────────────────────────────────────────

_SUCCESS_HTML = (
    b"<html><body style='font-family:sans-serif;text-align:center;margin-top:60px'>"
    b"<h2>Connected to Strava!</h2>"
    b"<p>You can close this tab and return to OpenCycleTrainer.</p>"
    b"</body></html>"
)

_ERROR_HTML = (
    b"<html><body style='font-family:sans-serif;text-align:center;margin-top:60px'>"
    b"<h2>Strava connection failed.</h2>"
    b"<p>Please return to OpenCycleTrainer and try again.</p>"
    b"</body></html>"
)


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path.startswith("/callback"):
            query_string = self.path.split("?", 1)[1] if "?" in self.path else ""
            self.server.callback_query_string = query_string  # type: ignore[attr-defined]
            self._respond(200, _SUCCESS_HTML)
            self.server.callback_received.set()  # type: ignore[attr-defined]
        else:
            self._respond(404, b"Not found")

    def _respond(self, status: int, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        pass  # suppress request logging


class _CallbackServer(http.server.HTTPServer):
    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self.callback_received: threading.Event = threading.Event()
        self.callback_query_string: str = ""


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _run_callback_server(port: int, timeout_seconds: float) -> tuple[str, str]:
    """Start the loopback server, wait for the callback, and return (code, state)."""
    server = _CallbackServer(("127.0.0.1", port), _CallbackHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        received = server.callback_received.wait(timeout=timeout_seconds)
    finally:
        server.shutdown()

    if not received:
        raise TimeoutError(
            f"Strava OAuth callback not received within {timeout_seconds:.0f} seconds. "
            "Did you authorize in the browser?"
        )

    return parse_callback(server.callback_query_string)


# ── token exchange and athlete fetch ─────────────────────────────────────────


def _exchange_code(credentials: StravaAppCredentials, code: str) -> StravaTokenBundle:
    from stravalib import Client  # noqa: PLC0415

    client = Client()
    token_response = client.exchange_code_for_token(
        client_id=credentials.client_id,
        client_secret=credentials.client_secret,
        code=code,
    )
    return StravaTokenBundle(
        access_token=str(token_response["access_token"]),
        refresh_token=str(token_response["refresh_token"]),
        expires_at=int(token_response["expires_at"]),
    )


def _fetch_athlete_name(access_token: str) -> str:
    try:
        from stravalib import Client  # noqa: PLC0415

        client = Client(access_token=access_token)
        athlete = client.get_athlete()
        first = getattr(athlete, "firstname", "") or ""
        last = getattr(athlete, "lastname", "") or ""
        return f"{first} {last}".strip()
    except Exception:
        return ""


# ── public entry point ────────────────────────────────────────────────────────


def run_oauth_flow(
    credentials: StravaAppCredentials,
    *,
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
) -> OAuthResult:
    """Run the full loopback OAuth flow.

    Blocks the calling thread until the user authorizes in the browser or the
    timeout elapses.  Intended to be called from a background thread.

    Raises:
        TimeoutError: if the browser callback is not received within ``timeout_seconds``.
        ValueError: if the OAuth state does not match.
        Exception: propagated from the Strava token exchange on failure.
    """
    state = generate_state()
    port = _find_free_port()
    redirect_uri = f"http://127.0.0.1:{port}/callback"

    _logger.info("Starting Strava OAuth flow (client_id=%s)", credentials.client_id)
    auth_url = build_auth_url(credentials, redirect_uri, state)
    webbrowser.open(auth_url)

    received_code, received_state = _run_callback_server(port, timeout_seconds)
    validate_state(state, received_state)

    token_bundle = _exchange_code(credentials, received_code)
    athlete_name = _fetch_athlete_name(token_bundle.access_token)

    _logger.info("Strava OAuth completed for athlete: %s", athlete_name or "<unknown>")
    return OAuthResult(token_bundle=token_bundle, athlete_name=athlete_name)

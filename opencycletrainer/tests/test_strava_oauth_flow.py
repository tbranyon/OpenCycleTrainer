from __future__ import annotations

import pytest

from opencycletrainer.integrations.strava.oauth_flow import (
    build_auth_url,
    generate_state,
    parse_callback,
    validate_state,
)
from opencycletrainer.integrations.strava.app_credentials import StravaAppCredentials


_FAKE_CREDENTIALS = StravaAppCredentials(client_id="123", client_secret="sec")


# ── generate_state ────────────────────────────────────────────────────────────


def test_generate_state_is_non_empty():
    assert len(generate_state()) > 0


def test_generate_state_is_unique():
    assert generate_state() != generate_state()


def test_generate_state_is_url_safe():
    state = generate_state()
    # URL-safe base64 alphabet only contains alphanumeric, _, -
    allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-=")
    assert all(c in allowed for c in state)


# ── parse_callback ────────────────────────────────────────────────────────────


def test_parse_callback_extracts_code_and_state():
    code, state = parse_callback("code=abc123&state=xyz456")
    assert code == "abc123"
    assert state == "xyz456"


def test_parse_callback_handles_leading_question_mark():
    code, state = parse_callback("?code=abc&state=xyz")
    assert code == "abc"
    assert state == "xyz"


def test_parse_callback_raises_on_missing_code():
    with pytest.raises(ValueError, match="code"):
        parse_callback("state=xyz")


def test_parse_callback_raises_on_missing_state():
    with pytest.raises(ValueError, match="state"):
        parse_callback("code=abc")


def test_parse_callback_raises_on_empty_query_string():
    with pytest.raises(ValueError):
        parse_callback("")


# ── validate_state ────────────────────────────────────────────────────────────


def test_validate_state_passes_on_match():
    validate_state("expected_state", "expected_state")  # should not raise


def test_validate_state_raises_on_mismatch():
    with pytest.raises(ValueError, match="state mismatch"):
        validate_state("expected", "wrong")


def test_validate_state_raises_on_empty_received():
    with pytest.raises(ValueError, match="state mismatch"):
        validate_state("expected", "")


# ── build_auth_url ────────────────────────────────────────────────────────────


def test_build_auth_url_contains_client_id():
    url = build_auth_url(_FAKE_CREDENTIALS, "http://127.0.0.1:9999/callback", "st8")
    assert "123" in url


def test_build_auth_url_contains_redirect_uri():
    url = build_auth_url(_FAKE_CREDENTIALS, "http://127.0.0.1:9999/callback", "st8")
    assert "127.0.0.1" in url


def test_build_auth_url_contains_state():
    url = build_auth_url(_FAKE_CREDENTIALS, "http://127.0.0.1:9999/callback", "my_state_token")
    assert "my_state_token" in url


def test_build_auth_url_targets_strava():
    url = build_auth_url(_FAKE_CREDENTIALS, "http://127.0.0.1:9999/callback", "st8")
    assert "strava.com" in url

"""Tests for the auth routes: login form, magic-link send/verify, logout."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from conftest import TEST_SECRET
from fastapi.testclient import TestClient

from odin import auth as _auth

_CSRF = "test-csrf-token"


def _seed_csrf(client: TestClient) -> dict[str, str]:
    """Set a CSRF cookie on the client and return matching form-data."""
    client.cookies.set("csrf_token", _CSRF)
    return {"csrf_token": _CSRF}


def _stateful_incr(mock_valkey: MagicMock) -> dict[str, int]:
    """Wire mock_valkey.incr to maintain real per-key counts; return the dict for inspection."""
    counts: dict[str, int] = {}

    async def _incr(key: str) -> int:
        counts[key] = counts.get(key, 0) + 1
        return counts[key]

    mock_valkey.incr = AsyncMock(side_effect=_incr)
    return counts


# ---------------------------------------------------------------------------
# Login page
# ---------------------------------------------------------------------------


def test_login_page_renders(client: TestClient) -> None:
    """GET /login renders the sign-in form."""
    response = client.get("/login")
    assert response.status_code == 200
    assert "Sign in" in response.text
    assert 'action="/auth/send-link"' in response.text


def test_login_page_shows_limit_message_when_reason_is_limit(client: TestClient) -> None:
    """GET /login?reason=limit shows the rate-limit notice."""
    response = client.get("/login?reason=limit")
    assert "free searches for today" in response.text


def test_login_page_sets_csrf_cookie(client: TestClient) -> None:
    """GET /login issues a csrf_token cookie so subsequent POSTs can match."""
    response = client.get("/login")
    assert "csrf_token" in response.cookies


def test_login_has_noindex_header(client: TestClient) -> None:
    """GET /login carries X-Robots-Tag: noindex; public pages do not."""
    login = client.get("/login")
    assert login.status_code == 200
    assert "noindex" in login.headers.get("x-robots-tag", "").lower()

    home = client.get("/")
    assert "x-robots-tag" not in {k.lower() for k in home.headers}


def test_status_bar_absent_for_anonymous_pages(client: TestClient) -> None:
    """Status bar is hidden when no session cookie is present."""
    response = client.get("/login")
    assert response.status_code == 200
    assert "status-bar" not in response.text
    assert "PILOT" not in response.text


# ---------------------------------------------------------------------------
# Magic-link send
# ---------------------------------------------------------------------------


@patch("odin.routes.auth.send_magic_link")
def test_send_link_renders_confirmation(mock_send: MagicMock, client: TestClient) -> None:
    """POST /auth/send-link renders a confirmation and calls send_magic_link."""
    mock_send.return_value = None
    response = client.post(
        "/auth/send-link",
        data={"email": "user@example.com", **_seed_csrf(client)},
    )
    assert response.status_code == 200
    assert "user@example.com" in response.text
    mock_send.assert_called_once()


@patch("odin.routes.auth.send_magic_link")
def test_send_link_normalizes_email(mock_send: MagicMock, client: TestClient) -> None:
    """POST /auth/send-link lowercases and strips the submitted email."""
    mock_send.return_value = None
    client.post(
        "/auth/send-link",
        data={"email": "  USER@EXAMPLE.COM  ", **_seed_csrf(client)},
    )
    called_email = mock_send.call_args[0][0]
    assert called_email == "user@example.com"


@patch("odin.routes.auth.send_magic_link")
def test_send_link_rejects_second_email_within_hour_silently(
    mock_send: MagicMock, client: TestClient, mock_valkey: MagicMock
) -> None:
    """Second magic-link request for the same email is silently dropped."""
    _stateful_incr(mock_valkey)
    mock_send.return_value = None
    csrf = _seed_csrf(client)

    first = client.post("/auth/send-link", data={"email": "user@example.com", **csrf})
    second = client.post("/auth/send-link", data={"email": "user@example.com", **csrf})

    assert first.status_code == 200
    assert second.status_code == 200
    assert "user@example.com" in second.text
    assert mock_send.call_count == 1


@patch("odin.routes.auth.send_magic_link")
def test_send_link_rejects_sixth_ip_within_hour(
    mock_send: MagicMock, client: TestClient, mock_valkey: MagicMock
) -> None:
    """Six different emails from the same IP within an hour: only five are sent."""
    _stateful_incr(mock_valkey)
    mock_send.return_value = None
    csrf = _seed_csrf(client)

    for i in range(6):
        client.post("/auth/send-link", data={"email": f"u{i}@example.com", **csrf})

    assert mock_send.call_count == 5


@patch("odin.routes.auth.send_magic_link")
def test_send_link_keys_ip_rate_limit_by_x_forwarded_for(
    mock_send: MagicMock, client: TestClient, mock_valkey: MagicMock
) -> None:
    """IP-keyed Valkey state uses the same X-Forwarded-For value the NODE cell displays.

    Pins the contract that anything keyed by request_ip(request) — magic-link rate
    limit, daily quota, anonymous history — flows through request.client.host after
    ProxyHeadersMiddleware resolves the trusted X-Forwarded-For chain. Without this,
    a future change that introduced a parallel IP source (e.g. reading the header
    directly) could silently diverge the display from the keys.
    """
    counts = _stateful_incr(mock_valkey)
    mock_send.return_value = None
    csrf = _seed_csrf(client)

    client.post(
        "/auth/send-link",
        data={"email": "user@example.com", **csrf},
        headers={"X-Forwarded-For": "198.51.100.7"},
    )

    assert "linkrate:ip:198.51.100.7" in counts


@patch("odin.routes.auth.send_magic_link")
def test_send_link_rejects_mismatched_csrf(mock_send: MagicMock, client: TestClient) -> None:
    """POST with a CSRF form value that does not match the cookie returns 403."""
    client.cookies.set("csrf_token", "real-token")
    response = client.post(
        "/auth/send-link",
        data={"email": "user@example.com", "csrf_token": "tampered"},
    )
    assert response.status_code == 403
    mock_send.assert_not_called()


# ---------------------------------------------------------------------------
# Magic-link verify
# ---------------------------------------------------------------------------


def test_auth_verify_sets_session_cookie_and_redirects(client: TestClient) -> None:
    """GET /auth/verify with a valid token sets odin_session and redirects to /."""
    token = _auth.generate_magic_token("user@example.com", TEST_SECRET)
    response = client.get(f"/auth/verify?token={token}", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert "odin_session" in response.cookies


def test_auth_verify_invalid_token_renders_error(client: TestClient) -> None:
    """GET /auth/verify with a bad token renders an error on the login page."""
    response = client.get("/auth/verify?token=garbage.token")
    assert response.status_code == 200
    assert "Invalid or expired" in response.text


@patch("odin.signups.record_signup")
def test_auth_verify_records_signup(mock_record: AsyncMock, client: TestClient) -> None:
    """A valid magic-link verify records the anonymized signup for that email."""
    token = _auth.generate_magic_token("user@example.com", TEST_SECRET)
    response = client.get(f"/auth/verify?token={token}", follow_redirects=False)
    assert response.status_code == 303
    mock_record.assert_awaited_once()
    assert mock_record.await_args is not None
    assert mock_record.await_args.args[1] == "user@example.com"


@patch("odin.signups.record_signup")
def test_auth_verify_invalid_token_records_nothing(
    mock_record: AsyncMock, client: TestClient
) -> None:
    """An invalid link must not record a signup."""
    response = client.get("/auth/verify?token=garbage.token")
    assert response.status_code == 200
    mock_record.assert_not_awaited()


def test_auth_verify_rejects_reused_token(client: TestClient, mock_valkey: MagicMock) -> None:
    """A magic-link token can only be redeemed once; replay falls through to login error."""
    # First call: jti claim succeeds (Valkey SET NX returns truthy).
    # Second call: jti already claimed (returns None / falsy).
    mock_valkey.set = AsyncMock(side_effect=[True, None])
    token = _auth.generate_magic_token("user@example.com", TEST_SECRET)

    first = client.get(f"/auth/verify?token={token}", follow_redirects=False)
    assert "odin_session=" in first.headers.get("set-cookie", "")

    second = client.get(f"/auth/verify?token={token}")
    assert "odin_session=" not in second.headers.get("set-cookie", "")
    assert "Invalid or expired link" in second.text


def test_session_cookie_has_secure_flag_when_enabled(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """/auth/verify sets odin_session with Secure when cookie_secure is True."""
    from odin.config import settings  # noqa: PLC0415

    monkeypatch.setattr(settings, "cookie_secure", True)
    token = _auth.generate_magic_token("user@example.com", TEST_SECRET)
    response = client.get(f"/auth/verify?token={token}", follow_redirects=False)
    set_cookie = response.headers.get("set-cookie", "")
    assert "odin_session=" in set_cookie
    assert "Secure" in set_cookie


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------


def test_logout_via_get_is_method_not_allowed(client: TestClient) -> None:
    """Logout is now POST-only to defend against link-based CSRF."""
    response = client.get("/auth/logout", follow_redirects=False)
    assert response.status_code == 405


def test_auth_logout_clears_session_and_redirects(client: TestClient) -> None:
    """POST /auth/logout deletes the session cookie and redirects to /."""
    csrf = _seed_csrf(client)
    response = client.post("/auth/logout", data=csrf, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/"

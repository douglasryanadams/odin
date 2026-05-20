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


def test_auth_verify_captures_login_ip_into_session(client: TestClient) -> None:
    """The /auth/verify response stores the link-clicker's IP in the session payload."""
    token = _auth.generate_magic_token("user@example.com", TEST_SECRET)
    response = client.get(f"/auth/verify?token={token}", follow_redirects=False)
    cookie = response.cookies.get("odin_session")
    assert cookie is not None
    session = _auth.verify_session_value(cookie, TEST_SECRET)
    assert session.email == "user@example.com"
    # Starlette's TestClient defaults the client host to "testclient"; we just want a value.
    assert session.ip


def test_auth_verify_honors_x_forwarded_for_for_session_ip(client: TestClient) -> None:
    """When fronted by a trusted proxy, request_ip resolves to X-Forwarded-For, not the TCP peer.

    Regression for the production symptom where session.ip captured the nginx docker-bridge
    address (172.21.0.6) instead of the real viewer IP forwarded by CloudFront -> nginx.
    """
    token = _auth.generate_magic_token("user@example.com", TEST_SECRET)
    response = client.get(
        f"/auth/verify?token={token}",
        headers={"X-Forwarded-For": "203.0.113.42"},
        follow_redirects=False,
    )
    cookie = response.cookies.get("odin_session")
    assert cookie is not None
    session = _auth.verify_session_value(cookie, TEST_SECRET)
    assert session.ip == "203.0.113.42"


def test_auth_verify_invalid_token_renders_error(client: TestClient) -> None:
    """GET /auth/verify with a bad token renders an error on the login page."""
    response = client.get("/auth/verify?token=garbage.token")
    assert response.status_code == 200
    assert "Invalid or expired" in response.text


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

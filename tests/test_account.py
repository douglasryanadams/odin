"""Tests for the authenticated account routes: dashboard, account delete."""

from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

from conftest import TEST_SECRET
from fastapi.testclient import TestClient

from odin import auth as _auth

_CSRF = "test-csrf-token"


def _seed_csrf(client: TestClient) -> dict[str, str]:
    """Set a CSRF cookie on the client and return matching form-data."""
    client.cookies.set("csrf_token", _CSRF)
    return {"csrf_token": _CSRF}


async def _async_iter(items: list[bytes]) -> AsyncIterator[bytes]:
    for item in items:
        yield item


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


def test_dashboard_redirects_unauthenticated_users(client: TestClient) -> None:
    """GET /dashboard redirects to /login when no valid session exists."""
    response = client.get("/dashboard", follow_redirects=False)
    assert response.status_code == 303
    assert "/login" in response.headers["location"]


def test_dashboard_renders_for_authenticated_user(client: TestClient) -> None:
    """GET /dashboard renders quota and history for a logged-in user."""
    session = _auth.create_session_value("user@example.com", TEST_SECRET)
    response = client.get("/dashboard", cookies={"odin_session": session})
    assert response.status_code == 200
    assert "user@example.com" in response.text
    assert "searches used today" in response.text


@patch("odin.history.get_history")
def test_dashboard_loads_history_for_the_signed_in_user(
    mock_get_history: AsyncMock, client: TestClient
) -> None:
    """The dashboard reads recent searches from Postgres keyed to the user's email."""
    mock_get_history.return_value = []
    session = _auth.create_session_value("user@example.com", TEST_SECRET)
    response = client.get("/dashboard", cookies={"odin_session": session})
    assert response.status_code == 200
    mock_get_history.assert_awaited_once()
    assert mock_get_history.await_args is not None
    requester = mock_get_history.await_args.args[1]
    assert requester.user_email == "user@example.com"


def test_dashboard_signout_uses_post_form(client: TestClient) -> None:
    """Sign out on the dashboard is a POST form, not a GET link, since /auth/logout is POST-only."""
    session = _auth.create_session_value("user@example.com", TEST_SECRET)
    response = client.get("/dashboard", cookies={"odin_session": session})
    assert response.status_code == 200
    assert 'href="/auth/logout"' not in response.text
    assert 'action="/auth/logout"' in response.text


def test_dashboard_shows_delete_account_form(client: TestClient) -> None:
    """Dashboard renders the delete-account form for authenticated users."""
    session = _auth.create_session_value("user@example.com", TEST_SECRET)
    response = client.get("/dashboard", cookies={"odin_session": session})
    assert response.status_code == 200
    assert 'action="/account/delete"' in response.text


def test_status_bar_renders_email_and_live_ip_for_authenticated_pages(
    client: TestClient,
) -> None:
    """The status bar shows the live X-Forwarded-For IP, not a session-derived value."""
    session = _auth.create_session_value("user@example.com", TEST_SECRET)
    response = client.get(
        "/dashboard",
        cookies={"odin_session": session},
        headers={"X-Forwarded-For": "198.51.100.7"},
    )
    assert response.status_code == 200
    body = response.text
    assert "status-bar" in body
    assert "PILOT" in body
    assert "user@example.com" in body
    assert "NODE" in body
    assert "198.51.100.7" in body


# ---------------------------------------------------------------------------
# Account delete
# ---------------------------------------------------------------------------


def test_account_delete_clears_data_and_logs_out(
    client: TestClient, mock_valkey: MagicMock
) -> None:
    """POST /account/delete: 303 to /, session cookie cleared, store.delete_user called."""
    email = "user@example.com"
    session = _auth.create_session_value(email, TEST_SECRET)
    mock_valkey.delete = AsyncMock(return_value=1)
    mock_valkey.scan_iter = MagicMock(return_value=_async_iter([b"rate:user:abc:2026-05-07"]))
    client.cookies.set("odin_session", session)
    csrf = _seed_csrf(client)

    response = client.post(
        "/account/delete",
        data={"email": email, **csrf},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/"
    set_cookie = response.headers.get("set-cookie", "")
    assert "odin_session=" in set_cookie
    mock_valkey.delete.assert_awaited()


@patch("odin.history.delete_user_history")
@patch("odin.signups.delete_signup")
def test_account_delete_removes_durable_rows(
    mock_delete_signup: AsyncMock,
    mock_delete_history: AsyncMock,
    client: TestClient,
    mock_valkey: MagicMock,
) -> None:
    """Account deletion also removes the user's signup and search-history rows."""
    email = "user@example.com"
    mock_valkey.delete = AsyncMock(return_value=0)
    mock_valkey.scan_iter = MagicMock(return_value=_async_iter([]))
    session = _auth.create_session_value(email, TEST_SECRET)
    client.cookies.set("odin_session", session)
    csrf = _seed_csrf(client)

    response = client.post(
        "/account/delete",
        data={"email": email, **csrf},
        follow_redirects=False,
    )

    assert response.status_code == 303
    mock_delete_signup.assert_awaited_once()
    assert mock_delete_signup.await_args is not None
    assert mock_delete_signup.await_args.args[1] == email
    mock_delete_history.assert_awaited_once()
    assert mock_delete_history.await_args is not None
    assert mock_delete_history.await_args.args[1] == email


def test_account_delete_rejects_email_mismatch(client: TestClient) -> None:
    """Submitting a non-matching email returns 400."""
    session = _auth.create_session_value("user@example.com", TEST_SECRET)
    client.cookies.set("odin_session", session)
    csrf = _seed_csrf(client)
    response = client.post(
        "/account/delete",
        data={"email": "wrong@example.com", **csrf},
        follow_redirects=False,
    )
    assert response.status_code == 400


def test_account_delete_rejects_missing_csrf(client: TestClient) -> None:
    """Without a matching CSRF token the endpoint returns 403."""
    session = _auth.create_session_value("user@example.com", TEST_SECRET)
    client.cookies.set("odin_session", session)
    client.cookies.set("csrf_token", "right")
    response = client.post(
        "/account/delete",
        data={"csrf_token": "wrong", "email": "user@example.com"},
    )
    assert response.status_code == 403


def test_account_delete_rejects_unauthenticated(client: TestClient) -> None:
    """Without a session cookie the endpoint redirects to /login."""
    csrf = _seed_csrf(client)
    response = client.post(
        "/account/delete",
        data={"email": "user@example.com", **csrf},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "/login" in response.headers["location"]

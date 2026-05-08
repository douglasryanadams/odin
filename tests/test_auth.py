"""Tests for HMAC-signed magic link and session cookie auth."""

from unittest.mock import MagicMock, patch

import pytest

from odin import auth

_SECRET = b"test-secret-key-32-bytes-padding!"


def test_magic_token_roundtrip() -> None:
    token = auth.generate_magic_token("user@example.com", _SECRET)
    claims = auth.verify_magic_token(token, _SECRET)
    assert claims.email == "user@example.com"


def test_magic_token_wrong_secret_raises() -> None:
    token = auth.generate_magic_token("user@example.com", _SECRET)
    with pytest.raises(ValueError, match="bad signature"):
        auth.verify_magic_token(token, b"wrong-secret")


def test_magic_token_expired_raises() -> None:
    with patch("odin.auth.time") as mock_time:
        mock_time.time.return_value = 0.0
        token = auth.generate_magic_token("user@example.com", _SECRET)
    with patch("odin.auth.time") as mock_time:
        mock_time.time.return_value = float(auth._MAGIC_TOKEN_TTL + 1)  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
        with pytest.raises(ValueError, match="token expired"):
            auth.verify_magic_token(token, _SECRET)


def test_magic_token_malformed_raises() -> None:
    with pytest.raises(ValueError, match="malformed token"):
        auth.verify_magic_token("notavalidtoken", _SECRET)


def test_magic_token_jti_is_unique() -> None:
    """Each token gets a fresh nonce so verifies don't collide across users."""
    a = auth.verify_magic_token(auth.generate_magic_token("a@example.com", _SECRET), _SECRET)
    b = auth.verify_magic_token(auth.generate_magic_token("a@example.com", _SECRET), _SECRET)
    assert a.jti
    assert b.jti
    assert a.jti != b.jti


def test_session_roundtrip() -> None:
    value = auth.create_session_value("user@example.com", _SECRET)
    assert auth.verify_session_value(value, _SECRET) == "user@example.com"


def test_session_expired_raises() -> None:
    with patch("odin.auth.time") as mock_time:
        mock_time.time.return_value = 0.0
        value = auth.create_session_value("user@example.com", _SECRET)
    with patch("odin.auth.time") as mock_time:
        mock_time.time.return_value = float(auth._SESSION_TTL + 1)  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
        with pytest.raises(ValueError, match="session expired"):
            auth.verify_session_value(value, _SECRET)


def _mock_request(cookie_value: str | None) -> MagicMock:
    request = MagicMock()
    request.cookies.get.return_value = cookie_value
    request.app.state.secret_key = _SECRET
    return request


def test_get_current_user_returns_email_for_valid_session() -> None:
    value = auth.create_session_value("user@example.com", _SECRET)
    request = _mock_request(value)
    assert auth.get_current_user(request) == "user@example.com"


def test_get_current_user_returns_none_when_no_cookie() -> None:
    request = _mock_request(None)
    assert auth.get_current_user(request) is None


def test_get_current_user_returns_none_for_invalid_cookie() -> None:
    request = _mock_request("garbage.value")
    assert auth.get_current_user(request) is None

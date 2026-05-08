"""HMAC-signed magic link tokens and session cookies."""

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from typing import Any, cast

from fastapi import Request

_MAGIC_TOKEN_TTL = 900  # 15 minutes
_SESSION_TTL = 60 * 60 * 24 * 30  # 30 days
_SESSION_COOKIE = "odin_session"


@dataclass(frozen=True)
class MagicTokenClaims:
    """Verified magic-link payload."""

    email: str
    jti: str
    exp: int


def generate_csrf_token() -> str:
    """Return an unguessable CSRF token suitable for the double-submit pattern."""
    return secrets.token_urlsafe(32)


def csrf_matches(cookie_token: str | None, form_token: str | None) -> bool:
    """Return True iff both values are present and equal under constant-time comparison."""
    if not cookie_token or not form_token:
        return False
    return hmac.compare_digest(cookie_token, form_token)


def _sign(payload: dict[str, Any], secret: bytes) -> str:
    body = (
        base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode())
        .decode()
        .rstrip("=")
    )
    sig = hmac.new(secret, body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def _verify(token: str, secret: bytes) -> dict[str, Any]:
    try:
        body, sig = token.rsplit(".", 1)
    except ValueError as exc:
        msg = "malformed token"
        raise ValueError(msg) from exc
    expected = hmac.new(secret, body.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        msg = "bad signature"
        raise ValueError(msg)
    padding = "=" * (-len(body) % 4)
    return cast("dict[str, Any]", json.loads(base64.urlsafe_b64decode(body + padding)))


def _check_expiry(payload: dict[str, Any], label: str) -> str:
    exp = payload.get("exp")
    if not isinstance(exp, (int, float)):
        msg = f"missing expiry in {label}"
        raise ValueError(msg)  # noqa: TRY004
    if time.time() > exp:
        msg = f"{label} expired"
        raise ValueError(msg)
    email = payload.get("email")
    if not isinstance(email, str):
        msg = f"missing email in {label}"
        raise ValueError(msg)  # noqa: TRY004
    return email


def generate_magic_token(email: str, secret: bytes) -> str:
    """Return a signed, time-limited token encoding the given email."""
    payload: dict[str, Any] = {
        "email": email,
        "exp": int(time.time()) + _MAGIC_TOKEN_TTL,
        "jti": secrets.token_urlsafe(16),
    }
    return _sign(payload, secret)


def verify_magic_token(token: str, secret: bytes) -> MagicTokenClaims:
    """Verify a token and return its claims, or raise ValueError."""
    payload = _verify(token, secret)
    email = _check_expiry(payload, "token")
    jti = payload.get("jti")
    if not isinstance(jti, str) or not jti:
        msg = "missing jti in token"
        raise ValueError(msg)
    return MagicTokenClaims(email=email, jti=jti, exp=int(payload["exp"]))


def create_session_value(email: str, secret: bytes) -> str:
    """Return a signed session cookie value encoding the given email."""
    payload: dict[str, Any] = {"email": email, "exp": int(time.time()) + _SESSION_TTL}
    return _sign(payload, secret)


def verify_session_value(value: str, secret: bytes) -> str:
    """Verify a session cookie value and return the encoded email, or raise ValueError."""
    return _check_expiry(_verify(value, secret), "session")


def get_current_user(request: Request) -> str | None:
    """Return the authenticated user's email from the session cookie, or None."""
    value = request.cookies.get(_SESSION_COOKIE)
    if not value:
        return None
    secret: bytes = request.app.state.secret_key
    try:
        return verify_session_value(value, secret)
    except ValueError:
        return None

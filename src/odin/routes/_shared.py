"""Cookie constants and helpers shared by more than one router module."""

import secrets

from fastapi import Request
from fastapi.responses import Response

from odin import auth
from odin.config import settings

ANON_COOKIE = "odin_anon"
ANON_COOKIE_MAX_AGE = 365 * 24 * 3600
CSRF_COOKIE = "csrf_token"
NOTICE_COOKIE = "odin_seen_notice"
NOTICE_COOKIE_MAX_AGE = 365 * 24 * 3600
MAX_QUERY_LEN = 256


def anon_cookie_id(request: Request) -> str:
    """Return the existing anonymous cookie value, or generate a fresh one."""
    return request.cookies.get(ANON_COOKIE) or secrets.token_urlsafe(16)


def request_ip(request: Request) -> str:
    """Return the client IP from the request, or '' when missing."""
    return request.client.host if request.client else ""


def user_email(user: auth.SessionUser | None) -> str | None:
    """Return the session user's email, or None when anonymous."""
    return user.email if user else None


def csrf_token_value(request: Request) -> str:
    """Return the CSRF token to embed in templates (existing cookie or a fresh value)."""
    return request.cookies.get(CSRF_COOKIE) or auth.generate_csrf_token()


def set_csrf_cookie_if_absent(request: Request, response: Response, token: str) -> None:
    """Persist the CSRF token in a cookie if the request didn't already carry one."""
    if request.cookies.get(CSRF_COOKIE):
        return
    response.set_cookie(
        CSRF_COOKIE,
        token,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        max_age=ANON_COOKIE_MAX_AGE,
    )

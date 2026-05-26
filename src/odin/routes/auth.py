"""Authentication routes: login form, magic-link send/verify, logout."""

from typing import Annotated

import asyncpg
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from valkey.asyncio import Valkey

from odin import auth as _auth
from odin import db, signups, store
from odin.app import get_valkey_client, templates
from odin.config import settings
from odin.email import send_magic_link
from odin.routes._shared import (
    CSRF_COOKIE,
    csrf_token_value,
    request_ip,
    set_csrf_cookie_if_absent,
)

router = APIRouter()


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, reason: str | None = None) -> HTMLResponse:
    """Render the login page with an optional reason message."""
    csrf = csrf_token_value(request)
    resp = templates.TemplateResponse(request, "login.html", {"reason": reason, "csrf_token": csrf})
    set_csrf_cookie_if_absent(request, resp, csrf)
    resp.headers["X-Robots-Tag"] = "noindex, nofollow"
    return resp


@router.post("/auth/send-link", response_class=HTMLResponse)
async def send_link(
    request: Request,
    email: Annotated[str, Form()],
    csrf_token: Annotated[str, Form()],
    valkey_client: Annotated[Valkey, Depends(get_valkey_client)],
) -> HTMLResponse:
    """Generate and send a magic sign-in link."""
    if not _auth.csrf_matches(request.cookies.get(CSRF_COOKIE), csrf_token):
        raise HTTPException(status_code=403, detail="CSRF check failed")
    email = email.strip().lower()
    if not email:
        return templates.TemplateResponse(
            request, "login.html", {"error": "Email address is required."}
        )
    sent_template = templates.TemplateResponse(
        request, "login.html", {"sent": True, "sent_email": email}
    )
    if not await store.claim_email_link_send(valkey_client, email, request_ip(request)):
        return sent_template
    token = _auth.generate_magic_token(email, request.app.state.secret_key)
    link = f"{settings.app_url}/auth/verify?token={token}"
    await send_magic_link(email, link)
    return sent_template


@router.get("/auth/verify", response_model=None)
async def auth_verify(
    request: Request,
    token: str,
    valkey_client: Annotated[Valkey, Depends(get_valkey_client)],
    db_pool: Annotated[asyncpg.Pool, Depends(db.get_db_pool)],
) -> Response:
    """Verify a magic link token and set the session cookie."""
    invalid = templates.TemplateResponse(
        request,
        "login.html",
        {"error": "Invalid or expired link. Please request a new one."},
    )
    try:
        claims = _auth.verify_magic_token(token, request.app.state.secret_key)
    except ValueError:
        return invalid
    if not await store.consume_magic_jti(valkey_client, claims.jti, claims.exp):
        return invalid
    # Ownership of the email is now proven; record the anonymized signup/sign-in.
    await signups.record_signup(db_pool, claims.email)
    session_value = _auth.create_session_value(claims.email, request.app.state.secret_key)
    resp = RedirectResponse(url="/", status_code=303)
    resp.set_cookie(
        "odin_session",
        session_value,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        max_age=30 * 24 * 3600,
    )
    return resp


@router.post("/auth/logout")
async def logout(
    request: Request,
    csrf_token: Annotated[str, Form()],
) -> Response:
    """Clear the session cookie and redirect home."""
    if not _auth.csrf_matches(request.cookies.get(CSRF_COOKIE), csrf_token):
        raise HTTPException(status_code=403, detail="CSRF check failed")
    resp = RedirectResponse(url="/", status_code=303)
    resp.delete_cookie("odin_session")
    return resp

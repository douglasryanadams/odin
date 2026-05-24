"""Static-ish pages: home, about, privacy, terms, health, notice dismissal."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from valkey.asyncio import Valkey

from odin import auth, store
from odin.app import get_valkey_client, templates
from odin.config import settings
from odin.routes._shared import (
    ANON_COOKIE,
    ANON_COOKIE_MAX_AGE,
    NOTICE_COOKIE,
    NOTICE_COOKIE_MAX_AGE,
    anon_cookie_id,
    csrf_token_value,
    request_ip,
    set_csrf_cookie_if_absent,
    user_email,
)

router = APIRouter()


@router.get("/", response_class=HTMLResponse, response_model=None)
async def index(
    request: Request,
    valkey_client: Annotated[Valkey, Depends(get_valkey_client)],
) -> HTMLResponse | RedirectResponse:
    """Render the home page; assign anonymous cookie on first visit."""
    user = auth.get_current_user(request)
    cookie_id = anon_cookie_id(request)
    used = await store.get_daily_count(
        valkey_client,
        user_email=user_email(user),
        cookie_id=cookie_id,
        ip_address=request_ip(request),
    )
    limit = settings.auth_daily_limit if user else settings.anon_daily_limit
    if not user and used >= limit:
        return RedirectResponse("/login?reason=limit", status_code=302)
    csrf = csrf_token_value(request)
    resp = templates.TemplateResponse(
        request,
        "index.html",
        {
            "user": user,
            "used": used,
            "limit": limit,
            "auth_limit": settings.auth_daily_limit,
            "csrf_token": csrf,
        },
    )
    if not request.cookies.get(ANON_COOKIE):
        resp.set_cookie(
            ANON_COOKIE,
            cookie_id,
            httponly=True,
            samesite="lax",
            secure=settings.cookie_secure,
            max_age=ANON_COOKIE_MAX_AGE,
        )
    set_csrf_cookie_if_absent(request, resp, csrf)
    return resp


@router.get("/health")
def health() -> dict[str, str]:
    """Return service health status."""
    return {"status": "ok"}


@router.get("/about", response_class=HTMLResponse)
async def about(request: Request) -> HTMLResponse:
    """Render the About page."""
    return templates.TemplateResponse(
        request,
        "about.html",
        {"user": auth.get_current_user(request)},
    )


@router.get("/privacy", response_class=HTMLResponse)
async def privacy(request: Request) -> HTMLResponse:
    """Render the privacy policy."""
    return templates.TemplateResponse(
        request,
        "privacy.html",
        {"user": auth.get_current_user(request), "contact_email": settings.contact_email},
    )


@router.get("/terms", response_class=HTMLResponse)
async def terms(request: Request) -> HTMLResponse:
    """Render the terms of service."""
    return templates.TemplateResponse(
        request,
        "terms.html",
        {"user": auth.get_current_user(request), "contact_email": settings.contact_email},
    )


@router.post("/notice/dismiss")
async def dismiss_notice(request: Request) -> RedirectResponse:
    """Set the disclosure-notice cookie and bounce back."""
    target = request.headers.get("referer") or "/"
    resp = RedirectResponse(url=target, status_code=303)
    resp.set_cookie(
        NOTICE_COOKIE,
        "1",
        httponly=False,
        samesite="lax",
        secure=settings.cookie_secure,
        max_age=NOTICE_COOKIE_MAX_AGE,
    )
    return resp

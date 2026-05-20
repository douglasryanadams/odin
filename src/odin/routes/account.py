"""Authenticated account routes: dashboard, account delete."""

from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from valkey.asyncio import Valkey

from odin import auth, store
from odin.app import get_valkey_client, templates
from odin.config import settings
from odin.routes._shared import (
    ANON_COOKIE,
    CSRF_COOKIE,
    csrf_token_value,
    request_ip,
    set_csrf_cookie_if_absent,
)

router = APIRouter()


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    valkey_client: Annotated[Valkey, Depends(get_valkey_client)],
) -> Response:
    """Render the usage dashboard for authenticated users."""
    user = auth.get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    cookie_id = request.cookies.get(ANON_COOKIE, "")
    ip_address = request_ip(request)
    used = await store.get_daily_count(
        valkey_client, user_email=user.email, cookie_id=cookie_id, ip_address=ip_address
    )
    history = await store.get_history(
        valkey_client, user_email=user.email, cookie_id=cookie_id, ip_address=ip_address
    )
    csrf = csrf_token_value(request)
    resp = templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "user": user,
            "used": used,
            "limit": settings.auth_daily_limit,
            "history": history,
            "csrf_token": csrf,
        },
    )
    set_csrf_cookie_if_absent(request, resp, csrf)
    return resp


@router.post("/account/delete")
async def account_delete(
    request: Request,
    csrf_token: Annotated[str, Form()],
    email: Annotated[str, Form()],
    valkey_client: Annotated[Valkey, Depends(get_valkey_client)],
) -> Response:
    """Delete all data tied to the signed-in user and clear the session."""
    user = auth.get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    if not auth.csrf_matches(request.cookies.get(CSRF_COOKIE), csrf_token):
        raise HTTPException(status_code=403, detail="CSRF check failed")
    if email.strip().lower() != user.email.lower():
        raise HTTPException(status_code=400, detail="Email does not match signed-in account")
    await store.delete_user(valkey_client, user.email)
    resp = RedirectResponse(url="/", status_code=303)
    resp.delete_cookie("odin_session")
    return resp

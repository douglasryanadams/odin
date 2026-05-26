"""Authenticated account routes: dashboard, account delete."""

from typing import Annotated

import asyncpg
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from valkey.asyncio import Valkey

from odin import auth, db, history, store
from odin.app import get_valkey_client, templates
from odin.config import settings
from odin.identity import Requester
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
    db_pool: Annotated[asyncpg.Pool, Depends(db.get_db_pool)],
) -> Response:
    """Render the usage dashboard for authenticated users."""
    user = auth.get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    requester = Requester(user.email, request.cookies.get(ANON_COOKIE, ""), request_ip(request))
    used = await store.get_daily_count(valkey_client, requester)
    recent = await history.get_history(db_pool, requester)
    csrf = csrf_token_value(request)
    resp = templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "user": user,
            "used": used,
            "limit": settings.auth_daily_limit,
            "history": recent,
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

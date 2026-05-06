"""Odin web application."""

import datetime
import json
import secrets
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from anthropic import AsyncAnthropic
from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from playwright.async_api import async_playwright
from valkey.asyncio import Valkey

from odin import auth, fetch, log, pipeline, store
from odin.config import settings
from odin.email import send_magic_link

log.setup()

_ANON_COOKIE = "odin_anon"
_ANON_COOKIE_MAX_AGE = 365 * 24 * 3600


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Launch Chromium and connect Valkey on startup; close both on shutdown."""
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=settings.playwright_headless)
        valkey_client = Valkey.from_url(settings.odin_valkey_url)
        app.state.browser = browser
        app.state.valkey = valkey_client
        app.state.secret_key = settings.secret_key.encode()
        try:
            yield
        finally:
            await browser.close()
            await valkey_client.aclose()


app = FastAPI(lifespan=lifespan)
app.mount(
    "/static",
    StaticFiles(directory=Path(__file__).parent / "static"),
    name="static",
)
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")


def get_searxng_url() -> str:
    """Return the SearXNG base URL from config."""
    return settings.searxng_url


def get_anthropic_client() -> AsyncAnthropic:
    """Return an Anthropic client using ANTHROPIC_API_KEY from the environment."""
    return AsyncAnthropic()


def get_page_fetcher(request: Request) -> fetch.PageFetcher:
    """Return a PlaywrightPageFetcher wrapping the per-worker Browser."""
    return fetch.PlaywrightPageFetcher(browser=request.app.state.browser)


def get_valkey_client(request: Request) -> Valkey:
    """Return the shared Valkey client from app state."""
    return request.app.state.valkey  # type: ignore[no-any-return]


def _anon_cookie_id(request: Request) -> str:
    return request.cookies.get(_ANON_COOKIE) or secrets.token_urlsafe(16)


def _ip(request: Request) -> str:
    return request.client.host if request.client else ""


@app.get("/", response_class=HTMLResponse, response_model=None)
async def index(
    request: Request,
    valkey_client: Annotated[Valkey, Depends(get_valkey_client)],
) -> HTMLResponse | RedirectResponse:
    """Render the home page; assign anonymous cookie on first visit."""
    user = auth.get_current_user(request)
    cookie_id = _anon_cookie_id(request)
    used = await store.get_daily_count(
        valkey_client, user_email=user, cookie_id=cookie_id, ip_address=_ip(request)
    )
    limit = settings.auth_daily_limit if user else settings.anon_daily_limit
    if not user and used >= limit:
        return RedirectResponse("/login?reason=limit", status_code=302)
    resp = templates.TemplateResponse(
        request,
        "index.html",
        {"user": user, "used": used, "limit": limit, "auth_limit": settings.auth_daily_limit},
    )
    if not request.cookies.get(_ANON_COOKIE):
        resp.set_cookie(
            _ANON_COOKIE, cookie_id, httponly=True, samesite="lax", max_age=_ANON_COOKIE_MAX_AGE
        )
    return resp


@app.get("/health")
def health() -> dict[str, str]:
    """Return service health status."""
    return {"status": "ok"}


@app.get("/profile", response_class=HTMLResponse)
async def profile_page(
    request: Request,
    q: str,
    valkey_client: Annotated[Valkey, Depends(get_valkey_client)],
) -> HTMLResponse:
    """Render the profile page; assign anonymous cookie on first visit."""
    user = auth.get_current_user(request)
    cookie_id = _anon_cookie_id(request)
    used = await store.get_daily_count(
        valkey_client, user_email=user, cookie_id=cookie_id, ip_address=_ip(request)
    )
    limit = settings.auth_daily_limit if user else settings.anon_daily_limit
    resp = templates.TemplateResponse(
        request,
        "profile.html",
        {
            "query": q,
            "user": user,
            "used": used,
            "limit": limit,
            "auth_limit": settings.auth_daily_limit,
        },
    )
    if not request.cookies.get(_ANON_COOKIE):
        resp.set_cookie(
            _ANON_COOKIE, cookie_id, httponly=True, samesite="lax", max_age=_ANON_COOKIE_MAX_AGE
        )
    return resp


@app.get("/profile/stream")
async def profile_stream(  # noqa: PLR0913
    request: Request,
    q: str,
    searxng_url: Annotated[str, Depends(get_searxng_url)],
    anthropic: Annotated[AsyncAnthropic, Depends(get_anthropic_client)],
    fetcher: Annotated[fetch.PageFetcher, Depends(get_page_fetcher)],
    valkey_client: Annotated[Valkey, Depends(get_valkey_client)],
) -> StreamingResponse:
    """Stream profile pipeline progress as Server-Sent Events."""
    user = auth.get_current_user(request)
    cookie_id = request.cookies.get(_ANON_COOKIE, "")
    ip_address = _ip(request)

    if await store.is_rate_limited(
        valkey_client,
        user_email=user,
        cookie_id=cookie_id,
        ip_address=ip_address,
        anon_limit=settings.anon_daily_limit,
        auth_limit=settings.auth_daily_limit,
    ):

        async def _rate_limited() -> AsyncGenerator[str, None]:
            payload = {"type": "rate_limited", "redirect": "/login?reason=limit"}
            yield f"data: {json.dumps(payload)}\n\n"

        return StreamingResponse(_rate_limited(), media_type="text/event-stream")

    async def event_generator() -> AsyncGenerator[str, None]:
        category = "other"
        async for event in pipeline.build_profile(q, searxng_url, anthropic, fetcher):
            if event.stage == "categorized":
                category = event.data.get("category", "other")
            payload = {"type": event.stage, **event.data}
            yield f"data: {json.dumps(payload)}\n\n"
        yield 'data: {"type": "done"}\n\n'
        await store.record_query(
            valkey_client, user_email=user, cookie_id=cookie_id, ip_address=ip_address
        )
        await store.push_history(
            valkey_client,
            user_email=user,
            cookie_id=cookie_id,
            ip_address=ip_address,
            entry={
                "q": q,
                "t": datetime.datetime.now(datetime.UTC).isoformat(),
                "cat": category,
            },
        )

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, reason: str | None = None) -> HTMLResponse:
    """Render the login page with an optional reason message."""
    return templates.TemplateResponse(request, "login.html", {"reason": reason})


@app.post("/auth/send-link", response_class=HTMLResponse)
async def send_link(
    request: Request,
    email: Annotated[str, Form()],
) -> HTMLResponse:
    """Generate and send a magic sign-in link."""
    email = email.strip().lower()
    if not email:
        return templates.TemplateResponse(
            request, "login.html", {"error": "Email address is required."}
        )
    token = auth.generate_magic_token(email, request.app.state.secret_key)
    link = f"{settings.app_url}/auth/verify?token={token}"
    await send_magic_link(email, link)
    return templates.TemplateResponse(request, "login.html", {"sent": True, "sent_email": email})


@app.get("/auth/verify")
async def auth_verify(request: Request, token: str) -> Response:
    """Verify a magic link token and set the session cookie."""
    try:
        email = auth.verify_magic_token(token, request.app.state.secret_key)
    except ValueError:
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Invalid or expired link. Please request a new one."},
        )
    session_value = auth.create_session_value(email, request.app.state.secret_key)
    resp = RedirectResponse(url="/", status_code=303)
    resp.set_cookie(
        "odin_session",
        session_value,
        httponly=True,
        samesite="lax",
        max_age=30 * 24 * 3600,
    )
    return resp


@app.get("/auth/logout")
async def logout() -> Response:
    """Clear the session cookie and redirect home."""
    resp = RedirectResponse(url="/", status_code=303)
    resp.delete_cookie("odin_session")
    return resp


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    valkey_client: Annotated[Valkey, Depends(get_valkey_client)],
) -> Response:
    """Render the usage dashboard for authenticated users."""
    user = auth.get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    cookie_id = request.cookies.get(_ANON_COOKIE, "")
    ip_address = _ip(request)
    used = await store.get_daily_count(
        valkey_client, user_email=user, cookie_id=cookie_id, ip_address=ip_address
    )
    history = await store.get_history(
        valkey_client, user_email=user, cookie_id=cookie_id, ip_address=ip_address
    )
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "user": user,
            "used": used,
            "limit": settings.auth_daily_limit,
            "history": history,
        },
    )

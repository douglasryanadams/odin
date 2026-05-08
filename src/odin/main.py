"""Odin web application."""

import datetime
import json
import secrets
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

from anthropic import AsyncAnthropic
from fastapi import Depends, FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from playwright.async_api import async_playwright
from valkey.asyncio import Valkey

from odin import auth, cache, fetch, log, pipeline, store
from odin.config import settings
from odin.email import send_magic_link

log.setup()

_ANON_COOKIE = "odin_anon"
_ANON_COOKIE_MAX_AGE = 365 * 24 * 3600
_MAX_QUERY_LEN = 256
_CSRF_COOKIE = "csrf_token"

_CSP = (
    "default-src 'self'; "
    "img-src 'self' data:; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdnjs.cloudflare.com; "
    "font-src 'self' https://fonts.gstatic.com https://cdnjs.cloudflare.com; "
    "script-src 'self'; "
    "connect-src 'self'; "
    "frame-ancestors 'none'"
)
_BASE_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Content-Security-Policy": _CSP,
}
_HSTS = "max-age=31536000; includeSubDomains"


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


@app.middleware("http")
async def _add_security_headers(  # pyright: ignore[reportUnusedFunction]
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    """Attach baseline security headers to every response."""
    response = await call_next(request)
    for key, value in _BASE_SECURITY_HEADERS.items():
        response.headers.setdefault(key, value)
    if settings.cookie_secure:
        response.headers.setdefault("Strict-Transport-Security", _HSTS)
    return response


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


def _csrf_token_value(request: Request) -> str:
    """Return the CSRF token to embed in templates (existing cookie or a fresh value)."""
    return request.cookies.get(_CSRF_COOKIE) or auth.generate_csrf_token()


def _set_csrf_cookie_if_absent(request: Request, response: Response, token: str) -> None:
    """Persist the CSRF token in a cookie if the request didn't already carry one."""
    if request.cookies.get(_CSRF_COOKIE):
        return
    response.set_cookie(
        _CSRF_COOKIE,
        token,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        max_age=_ANON_COOKIE_MAX_AGE,
    )


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
    csrf = _csrf_token_value(request)
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
    if not request.cookies.get(_ANON_COOKIE):
        resp.set_cookie(
            _ANON_COOKIE,
            cookie_id,
            httponly=True,
            samesite="lax",
            secure=settings.cookie_secure,
            max_age=_ANON_COOKIE_MAX_AGE,
        )
    _set_csrf_cookie_if_absent(request, resp, csrf)
    return resp


@app.get("/health")
def health() -> dict[str, str]:
    """Return service health status."""
    return {"status": "ok"}


@app.get("/privacy", response_class=HTMLResponse)
async def privacy(request: Request) -> HTMLResponse:
    """Render the privacy policy."""
    return templates.TemplateResponse(
        request, "privacy.html", {"user": auth.get_current_user(request)}
    )


@app.get("/terms", response_class=HTMLResponse)
async def terms(request: Request) -> HTMLResponse:
    """Render the terms of service."""
    return templates.TemplateResponse(
        request, "terms.html", {"user": auth.get_current_user(request)}
    )


@app.get("/profile", response_class=HTMLResponse)
async def profile_page(
    request: Request,
    q: Annotated[str, Query(max_length=_MAX_QUERY_LEN)],
    valkey_client: Annotated[Valkey, Depends(get_valkey_client)],
) -> HTMLResponse:
    """Render the profile page; assign anonymous cookie on first visit."""
    user = auth.get_current_user(request)
    cookie_id = _anon_cookie_id(request)
    used = await store.get_daily_count(
        valkey_client, user_email=user, cookie_id=cookie_id, ip_address=_ip(request)
    )
    limit = settings.auth_daily_limit if user else settings.anon_daily_limit
    csrf = _csrf_token_value(request)
    resp = templates.TemplateResponse(
        request,
        "profile.html",
        {
            "query": q,
            "user": user,
            "used": used,
            "limit": limit,
            "auth_limit": settings.auth_daily_limit,
            "csrf_token": csrf,
        },
    )
    if not request.cookies.get(_ANON_COOKIE):
        resp.set_cookie(
            _ANON_COOKIE,
            cookie_id,
            httponly=True,
            samesite="lax",
            secure=settings.cookie_secure,
            max_age=_ANON_COOKIE_MAX_AGE,
        )
    _set_csrf_cookie_if_absent(request, resp, csrf)
    return resp


@app.get("/profile/stream")
async def profile_stream(  # noqa: PLR0913
    request: Request,
    q: Annotated[str, Query(max_length=_MAX_QUERY_LEN)],
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
        cached = await cache.get(valkey_client, q)
        if cached is not None:
            async for chunk in _replay_cached(cached):
                yield chunk
            category = _category_from(cached)
        else:
            collected: list[dict[str, Any]] = []
            category = "other"
            async for chunk in _stream_pipeline(q, searxng_url, anthropic, fetcher, collected):
                yield chunk
            category = _category_from(collected) or category
            if not _had_failure(collected):
                await cache.put(valkey_client, q, collected)
        await _record_completed_query(valkey_client, user, cookie_id, ip_address, q, category)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


async def _replay_cached(events: list[dict[str, Any]]) -> AsyncGenerator[str, None]:
    for payload in events:
        yield f"data: {json.dumps(payload)}\n\n"
    yield 'data: {"type": "done"}\n\n'


async def _stream_pipeline(
    q: str,
    searxng_url: str,
    anthropic: AsyncAnthropic,
    fetcher: fetch.PageFetcher,
    collected: list[dict[str, Any]],
) -> AsyncGenerator[str, None]:
    async for event in pipeline.build_profile(q, searxng_url, anthropic, fetcher):
        payload = {"type": event.stage, **event.data}
        collected.append(payload)
        yield f"data: {json.dumps(payload)}\n\n"
    yield 'data: {"type": "done"}\n\n'


def _category_from(events: list[dict[str, Any]]) -> str:
    for e in events:
        if e.get("type") == "categorized":
            value = e.get("category", "other")
            return value if isinstance(value, str) else "other"
    return "other"


def _had_failure(events: list[dict[str, Any]]) -> bool:
    return any(e.get("type") == "service_unavailable" for e in events)


async def _record_completed_query(  # noqa: PLR0913
    valkey_client: Valkey,
    user: str | None,
    cookie_id: str,
    ip_address: str,
    q: str,
    category: str,
) -> None:
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


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, reason: str | None = None) -> HTMLResponse:
    """Render the login page with an optional reason message."""
    csrf = _csrf_token_value(request)
    resp = templates.TemplateResponse(request, "login.html", {"reason": reason, "csrf_token": csrf})
    _set_csrf_cookie_if_absent(request, resp, csrf)
    return resp


@app.post("/auth/send-link", response_class=HTMLResponse)
async def send_link(
    request: Request,
    email: Annotated[str, Form()],
    csrf_token: Annotated[str, Form()],
    valkey_client: Annotated[Valkey, Depends(get_valkey_client)],
) -> HTMLResponse:
    """Generate and send a magic sign-in link."""
    if not auth.csrf_matches(request.cookies.get(_CSRF_COOKIE), csrf_token):
        raise HTTPException(status_code=403, detail="CSRF check failed")
    email = email.strip().lower()
    if not email:
        return templates.TemplateResponse(
            request, "login.html", {"error": "Email address is required."}
        )
    sent_template = templates.TemplateResponse(
        request, "login.html", {"sent": True, "sent_email": email}
    )
    if not await store.claim_email_link_send(valkey_client, email, _ip(request)):
        return sent_template
    token = auth.generate_magic_token(email, request.app.state.secret_key)
    link = f"{settings.app_url}/auth/verify?token={token}"
    await send_magic_link(email, link)
    return sent_template


@app.get("/auth/verify", response_model=None)
async def auth_verify(
    request: Request,
    token: str,
    valkey_client: Annotated[Valkey, Depends(get_valkey_client)],
) -> Response:
    """Verify a magic link token and set the session cookie."""
    invalid = templates.TemplateResponse(
        request,
        "login.html",
        {"error": "Invalid or expired link. Please request a new one."},
    )
    try:
        claims = auth.verify_magic_token(token, request.app.state.secret_key)
    except ValueError:
        return invalid
    if not await store.consume_magic_jti(valkey_client, claims.jti, claims.exp):
        return invalid
    session_value = auth.create_session_value(claims.email, request.app.state.secret_key)
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


@app.post("/auth/logout")
async def logout(
    request: Request,
    csrf_token: Annotated[str, Form()],
) -> Response:
    """Clear the session cookie and redirect home."""
    if not auth.csrf_matches(request.cookies.get(_CSRF_COOKIE), csrf_token):
        raise HTTPException(status_code=403, detail="CSRF check failed")
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
    csrf = _csrf_token_value(request)
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
    _set_csrf_cookie_if_absent(request, resp, csrf)
    return resp

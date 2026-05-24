"""FastAPI application, lifespan, templates, security middleware, and dependency providers.

`odin.main:app` re-exports `app` from this module; `odin.routes` registers the
individual route modules with it.
"""

from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from anthropic import AsyncAnthropic
from fastapi import FastAPI, Request
from fastapi.responses import Response
from fastapi.templating import Jinja2Templates
from playwright.async_api import async_playwright
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
from valkey.asyncio import Valkey

from odin import curl_fetch, fetch, log, search
from odin.config import settings

log.setup()

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

_HARDENED_LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--disable-features=IsolateOrigins,site-per-process",
]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Launch hardened Chrome and connect Valkey on startup; close both on shutdown."""
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            channel=settings.playwright_channel,
            headless=settings.playwright_headless,
            args=_HARDENED_LAUNCH_ARGS,
        )
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
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
templates.env.globals["app_url"] = settings.app_url  # pyright: ignore[reportArgumentType]


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


# Trust X-Forwarded-For / X-Forwarded-Proto from any upstream: the web container
# is only reachable across the compose network (nginx fronts it; CloudFront fronts
# nginx), so the TCP peer is always a proxy. Without this, request.client.host
# resolves to the docker bridge IP of nginx instead of the real viewer.
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")


def get_search_aggregator() -> search.SearchAggregator:
    """Return the search aggregator built from the backends enabled in config."""
    return search.build_aggregator(settings)


def get_anthropic_client() -> AsyncAnthropic:
    """Return an Anthropic client using ANTHROPIC_API_KEY from the environment."""
    return AsyncAnthropic()


def get_page_fetcher(request: Request) -> fetch.PageFetcher:
    """Return a tiered fetcher: curl_cffi first, hardened Playwright as fallback."""
    playwright = fetch.PlaywrightPageFetcher(
        browser=request.app.state.browser,
        storage_state_path=settings.playwright_storage_state_path,
    )
    return fetch.TieredPageFetcher(
        curl=curl_fetch.CurlCffiPageFetcher(),
        playwright=playwright,
        curl_enabled=settings.fetch_curl_cffi_enabled,
    )


def get_valkey_client(request: Request) -> Valkey:
    """Return the shared Valkey client from app state."""
    return request.app.state.valkey  # type: ignore[no-any-return]

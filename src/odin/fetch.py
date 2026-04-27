"""Web page fetching and content extraction via Playwright + trafilatura."""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import trafilatura
from loguru import logger
from playwright.async_api import (
    Browser,
    BrowserContext,
    Request,
    Route,
    ViewportSize,
)
from playwright.async_api import Error as PlaywrightError

CONTENT_LIMIT = 10_000
GOTO_TIMEOUT_MS = 15_000
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)
VIEWPORT: ViewportSize = {"width": 1280, "height": 800}
HEAVY_RESOURCES = frozenset({"image", "media", "font", "stylesheet"})


class PageFetcher(Protocol):
    """Fetches a list of URLs and returns extracted text per URL."""

    async def fetch_pages(self, urls: list[str]) -> dict[str, str]:
        """Return a dict mapping each URL to its extracted text or an error string."""
        ...


async def _block_heavy(route: Route, request: Request) -> None:
    if request.resource_type in HEAVY_RESOURCES:
        await route.abort()
    else:
        await route.continue_()


async def _fetch_one(context: BrowserContext, url: str) -> tuple[str, str]:
    page = await context.new_page()
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=GOTO_TIMEOUT_MS)
        html = await page.content()
        extracted = trafilatura.extract(html)
        text = extracted or html
        chars = min(len(text), CONTENT_LIMIT)
        logger.debug("fetch ok url={!r} chars={}", url, chars)
        return url, text[:CONTENT_LIMIT]
    except PlaywrightError as exc:
        logger.debug("fetch error url={!r} error={}", url, exc)
        return url, f"Error fetching URL: {exc}"
    finally:
        await page.close()


async def _fetch_pages_playwright(urls: list[str], browser: Browser) -> dict[str, str]:
    context = await browser.new_context(user_agent=USER_AGENT, viewport=VIEWPORT)
    await context.route("**/*", _block_heavy)
    trace_dir = os.getenv("PLAYWRIGHT_TRACE_DIR")
    if trace_dir:
        await context.tracing.start(screenshots=True, snapshots=True, sources=True)
    try:
        results = await asyncio.gather(*[_fetch_one(context, url) for url in urls])
    finally:
        if trace_dir:
            trace_path = Path(trace_dir) / f"trace-{int(time.time())}-{uuid.uuid4().hex[:8]}.zip"
            trace_path.parent.mkdir(parents=True, exist_ok=True)
            await context.tracing.stop(path=str(trace_path))
        await context.close()
    return dict(results)


@dataclass(frozen=True)
class PlaywrightPageFetcher:
    """Production PageFetcher backed by a shared Playwright browser."""

    browser: Browser

    async def fetch_pages(self, urls: list[str]) -> dict[str, str]:
        """Render and extract text from URLs in parallel using a fresh BrowserContext."""
        return await _fetch_pages_playwright(urls, self.browser)

"""Hardened Playwright page fetching plus tiered orchestration.

Two public fetchers live here:

* :class:`PlaywrightPageFetcher` — Tier 1. Renders the page in a real-Chrome
  context with locale, timezone, viewport jitter, an ``Accept-Language`` header,
  no resource blocking, a ``navigator.webdriver`` init script, and an optional
  shared ``storage_state`` JSON file persisted under an ``fcntl`` lock.
* :class:`TieredPageFetcher` — composes a Tier 0 fetcher (``curl_cffi``) with
  Tier 1 (Playwright). A URL only reaches Playwright if Tier 0 set its
  ``fall_back`` flag.

The Tier 0 fetcher itself lives in :mod:`odin.curl_fetch`. The runtime import
of that module would cycle, so the ``CurlFetchResult`` reference here is
TYPE_CHECKING-guarded.
"""

from __future__ import annotations

import asyncio
import fcntl
import json
import secrets
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Protocol

import trafilatura
from loguru import logger
from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    StorageState,
    ViewportSize,
)
from playwright.async_api import Error as PlaywrightError

from odin.config import settings

if TYPE_CHECKING:
    from odin.curl_fetch import CurlFetchResult

CONTENT_LIMIT = 10_000
GOTO_TIMEOUT_MS = 8_000
LOCK_TIMEOUT_SECONDS = 2.0
LOCK_RETRY_INTERVAL_SECONDS = 0.05
RETRY_MIN_CONTENT_CHARS = 100

VIEWPORT_ANCHORS: list[tuple[int, int]] = [(1366, 768), (1536, 864), (1440, 900)]
VIEWPORT_JITTER_PX = 20
_rand = secrets.SystemRandom()

WaitUntil = Literal["commit", "domcontentloaded", "load", "networkidle"]

LOCALE = "en-US"
TIMEZONE = "America/Los_Angeles"
EXTRA_HEADERS = {"Accept-Language": "en-US,en;q=0.9"}
NAVIGATOR_WEBDRIVER_INIT = "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"


class PageFetcher(Protocol):
    """Fetches a list of URLs and returns extracted text per URL."""

    async def fetch_pages(self, urls: list[str]) -> dict[str, str]:
        """Return a dict mapping each URL to its extracted text or an error string."""
        ...


class CurlFetcher(Protocol):
    """Tier 0 fetcher Protocol — returns per-URL text with a fallback flag."""

    async def fetch_pages(self, urls: list[str]) -> dict[str, CurlFetchResult]:
        """Fetch each URL via curl_cffi and flag those that should retry on Playwright."""
        ...


def extract_or_html(html: str, limit: int = CONTENT_LIMIT) -> str:
    """Return trafilatura-extracted text, falling back to raw HTML, capped at ``limit``."""
    extracted = trafilatura.extract(html)
    text = extracted or html
    return text[:limit]


def choose_viewport() -> ViewportSize:
    """Pick a viewport anchor at random and jitter it by up to ``VIEWPORT_JITTER_PX``."""
    width, height = _rand.choice(VIEWPORT_ANCHORS)
    width += _rand.randint(-VIEWPORT_JITTER_PX, VIEWPORT_JITTER_PX)
    height += _rand.randint(-VIEWPORT_JITTER_PX, VIEWPORT_JITTER_PX)
    return {"width": width, "height": height}


def _read_storage_state(path: str | None) -> StorageState | None:
    if path is None:
        return None
    state_path = Path(path)
    if not state_path.exists():
        return None
    try:
        loaded: StorageState = json.loads(state_path.read_text())
    except (json.JSONDecodeError, OSError):
        logger.warning("storage_state file unreadable, ignoring: {}", path)
        return None
    return loaded


async def _acquire_lock(lockfile_fd: int, deadline: float) -> bool:
    while True:
        try:
            fcntl.flock(lockfile_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            if time.monotonic() >= deadline:
                return False
            await asyncio.sleep(LOCK_RETRY_INTERVAL_SECONDS)
        else:
            return True


async def _persist_storage_state(context: BrowserContext, path: str) -> None:
    """Atomically persist storage_state under an exclusive ``flock`` with timeout."""
    state_path = Path(path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = state_path.with_name(state_path.name + ".lock")
    lock_path.touch()
    deadline = time.monotonic() + LOCK_TIMEOUT_SECONDS
    with lock_path.open("wb") as lockfile:
        if not await _acquire_lock(lockfile.fileno(), deadline):
            logger.warning("storage_state lock timeout, skipping persist: {}", path)
            return
        tmp_path = state_path.with_name(state_path.name + ".tmp")
        await context.storage_state(path=str(tmp_path))
        tmp_path.replace(state_path)


async def _attempt_goto(page: Page, url: str, wait_until: WaitUntil) -> str:
    await page.goto(url, wait_until=wait_until, timeout=GOTO_TIMEOUT_MS)
    html = await page.content()
    return extract_or_html(html, CONTENT_LIMIT)


async def _fetch_one(context: BrowserContext, url: str) -> tuple[str, str]:
    page = await context.new_page()
    try:
        try:
            text = await _attempt_goto(page, url, "domcontentloaded")
        except PlaywrightError as exc:
            logger.debug("fetch dom error url={!r} error={}", url, exc)
            text = ""
        if len(text) < RETRY_MIN_CONTENT_CHARS:
            try:
                text = await _attempt_goto(page, url, "load")
            except PlaywrightError as exc:
                logger.debug("fetch load error url={!r} error={}", url, exc)
                return url, f"Error fetching URL: {exc}"
        logger.debug("fetch ok url={!r} chars={}", url, len(text))
        return url, text
    finally:
        await page.close()


async def _new_hardened_context(browser: Browser, storage_state_path: str | None) -> BrowserContext:
    context = await browser.new_context(
        viewport=choose_viewport(),
        locale=LOCALE,
        timezone_id=TIMEZONE,
        extra_http_headers=EXTRA_HEADERS,
        storage_state=_read_storage_state(storage_state_path),
    )
    await context.add_init_script(NAVIGATOR_WEBDRIVER_INIT)
    return context


async def _maybe_start_tracing(context: BrowserContext) -> bool:
    if not settings.playwright_trace_dir:
        return False
    await context.tracing.start(screenshots=True, snapshots=True, sources=True)
    return True


async def _maybe_stop_tracing(context: BrowserContext, *, tracing_on: bool) -> None:
    if not tracing_on or not settings.playwright_trace_dir:
        return
    trace_path = (
        Path(settings.playwright_trace_dir) / f"trace-{int(time.time())}-{uuid.uuid4().hex[:8]}.zip"
    )
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    await context.tracing.stop(path=str(trace_path))


async def _fetch_pages_playwright(
    urls: list[str], browser: Browser, storage_state_path: str | None
) -> dict[str, str]:
    context = await _new_hardened_context(browser, storage_state_path)
    tracing_on = await _maybe_start_tracing(context)
    try:
        results = await asyncio.gather(*[_fetch_one(context, url) for url in urls])
    finally:
        await _maybe_stop_tracing(context, tracing_on=tracing_on)
        if storage_state_path:
            await _persist_storage_state(context, storage_state_path)
        await context.close()
    return dict(results)


@dataclass(frozen=True)
class PlaywrightPageFetcher:
    """Tier 1 fetcher: real-Chrome Playwright with persistent ``storage_state``."""

    browser: Browser
    storage_state_path: str | None = None

    async def fetch_pages(self, urls: list[str]) -> dict[str, str]:
        """Render and extract text from URLs in parallel using a fresh ``BrowserContext``."""
        if not urls:
            return {}
        return await _fetch_pages_playwright(urls, self.browser, self.storage_state_path)


@dataclass(frozen=True)
class TieredPageFetcher:
    """Compose a Tier 0 curl_cffi fetcher with a Tier 1 Playwright fetcher.

    URLs first try Tier 0; only those whose result has ``fall_back=True`` are
    retried in Tier 1. The final dict preserves the input URL order.
    """

    curl: CurlFetcher
    playwright: PageFetcher
    curl_enabled: bool = True

    async def fetch_pages(self, urls: list[str]) -> dict[str, str]:
        """Run each URL through Tier 0, then Tier 1 only for those that fell back."""
        if not urls:
            return {}
        if not self.curl_enabled:
            return await self.playwright.fetch_pages(urls)
        curl_results = await self.curl.fetch_pages(urls)
        fallback_urls = [u for u in urls if curl_results[u].fall_back]
        pw_results = await self.playwright.fetch_pages(fallback_urls) if fallback_urls else {}
        return {u: pw_results.get(u, curl_results[u].text) for u in urls}

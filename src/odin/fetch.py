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
LOCK_POLL_INTERVAL_SECONDS = 0.05
# Hard cap on the lock-poll loop so it always exits, even if the monotonic
# clock somehow fails to advance. At LOCK_POLL_INTERVAL_SECONDS=0.05 and
# LOCK_TIMEOUT_SECONDS=2.0 the deadline normally trips after ~40 iterations;
# 200 gives 5x headroom without spinning forever.
LOCK_POLL_MAX_ITERATIONS = 200
# Named only because ruff's PLR2004 forbids bare comparison literals.
_RETRY_MIN_CHARS = 100
VIEWPORT_ANCHORS: list[tuple[int, int]] = [(1366, 768), (1536, 864), (1440, 900)]
VIEWPORT_JITTER_PX = 20
_rand = secrets.SystemRandom()

WaitUntil = Literal["commit", "domcontentloaded", "load", "networkidle"]


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


def choose_viewport() -> ViewportSize:
    """Pick a viewport anchor at random and jitter it by up to ``VIEWPORT_JITTER_PX``."""
    width, height = _rand.choice(VIEWPORT_ANCHORS)
    width += _rand.randint(-VIEWPORT_JITTER_PX, VIEWPORT_JITTER_PX)
    height += _rand.randint(-VIEWPORT_JITTER_PX, VIEWPORT_JITTER_PX)
    return {"width": width, "height": height}


async def _attempt_goto(page: Page, url: str, wait_until: WaitUntil) -> str:
    await page.goto(url, wait_until=wait_until, timeout=GOTO_TIMEOUT_MS)
    html = await page.content()
    extracted = trafilatura.extract(html)
    return (extracted or html)[:CONTENT_LIMIT]


async def _fetch_one(context: BrowserContext, url: str) -> tuple[str, str]:
    page = await context.new_page()
    try:
        try:
            text = await _attempt_goto(page, url, "domcontentloaded")
        except PlaywrightError as exc:
            logger.debug("fetch dom error url={!r} error={}", url, exc)
            text = ""
        # Retry once on a near-empty result — domcontentloaded can return before
        # SPA content paints; "load" waits for full network + onload.
        if len(text) < _RETRY_MIN_CHARS:
            try:
                text = await _attempt_goto(page, url, "load")
            except PlaywrightError as exc:
                logger.debug("fetch load error url={!r} error={}", url, exc)
                return url, f"Error fetching URL: {exc}"
        logger.debug("fetch ok url={!r} chars={}", url, len(text))
        return url, text
    finally:
        await page.close()


async def _acquire_lock(lockfile_fd: int, deadline: float) -> bool:
    """Poll for an exclusive flock with bounded retries.

    Exits when the lock is acquired, the deadline elapses, or
    :data:`LOCK_POLL_MAX_ITERATIONS` is exhausted.
    """
    for _ in range(LOCK_POLL_MAX_ITERATIONS):
        try:
            fcntl.flock(lockfile_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            if time.monotonic() >= deadline:
                return False
            await asyncio.sleep(LOCK_POLL_INTERVAL_SECONDS)
        else:
            return True
    logger.warning("storage_state lock poll exceeded {} iterations", LOCK_POLL_MAX_ITERATIONS)
    return False


async def _persist_storage_state(context: BrowserContext, path: str) -> None:
    """Atomically write storage_state under an exclusive flock with timeout.

    A worker that can't grab the lock within ``LOCK_TIMEOUT_SECONDS`` logs and
    returns; cookies are domain-scoped so a missed write is recovered on the
    next visit.
    """
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


@dataclass(frozen=True)
class PlaywrightPageFetcher:
    """Tier 1 fetcher: hardened Playwright with persistent ``storage_state``."""

    browser: Browser
    storage_state_path: str | None = None

    async def fetch_pages(self, urls: list[str]) -> dict[str, str]:
        """Render and extract text from URLs in parallel using a fresh ``BrowserContext``."""
        if not urls:
            return {}

        # ASYNC240 (sync I/O in async fn) is suppressed for the two reads
        # below: state.json is a small (<10 KB) local-volume file, the cost
        # of a thread hop would dwarf the actual syscall, and this code path
        # runs once per batch on startup, not in the request hot loop.
        storage: StorageState | None = None
        if self.storage_state_path:
            state_path = Path(self.storage_state_path)
            if state_path.exists():  # noqa: ASYNC240
                try:
                    storage = json.loads(state_path.read_text())  # noqa: ASYNC240
                except (json.JSONDecodeError, OSError):
                    logger.warning(
                        "storage_state file unreadable, ignoring: {}", self.storage_state_path
                    )

        context = await self.browser.new_context(
            viewport=choose_viewport(),
            locale="en-US",
            timezone_id="America/Los_Angeles",
            extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
            storage_state=storage,
        )
        await context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        )

        trace_dir = settings.playwright_trace_dir
        if trace_dir:
            await context.tracing.start(screenshots=True, snapshots=True, sources=True)

        try:
            results = await asyncio.gather(*[_fetch_one(context, url) for url in urls])
        finally:
            if trace_dir:
                trace_path = (
                    Path(trace_dir) / f"trace-{int(time.time())}-{uuid.uuid4().hex[:8]}.zip"
                )
                trace_path.parent.mkdir(parents=True, exist_ok=True)
                await context.tracing.stop(path=str(trace_path))

            if self.storage_state_path:
                await _persist_storage_state(context, self.storage_state_path)
            await context.close()
        return dict(results)


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

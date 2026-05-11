"""Tier 0 fetcher using ``curl_cffi`` with Chrome TLS/JA3 impersonation.

``curl_cffi`` replicates a real Chrome browser's TLS handshake, JA3 fingerprint,
and HTTP/2 settings at the protocol level. This defeats the most common static
anti-bot checks (basic Cloudflare, Akamai) without the cost of running a full
browser. Pages that look like a bot wall or return ``status >= 400`` are
flagged for fallback to the Playwright tier.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass

import trafilatura
from curl_cffi.requests import AsyncSession, Response
from curl_cffi.requests.exceptions import RequestException
from loguru import logger

from odin.fetch import CONTENT_LIMIT

CURL_TIMEOUT_SECONDS = 8.0
BOT_WALL_SCAN_BYTES = 4096
LOW_EXTRACTION_THRESHOLD = 200
HEAVY_HTML_THRESHOLD = 5000
FALLBACK_STATUS_THRESHOLD = 400

_BOT_WALL_PATTERN = re.compile(
    r"just a moment|enable javascript|access denied|attention required|verify you are human",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class CurlFetchResult:
    """Result of one curl_cffi fetch attempt.

    ``text`` is the trafilatura extraction (or raw HTML fallback) capped at
    :data:`odin.fetch.CONTENT_LIMIT`. ``fall_back`` is True when the result
    should be retried via Playwright.
    """

    text: str
    fall_back: bool


def should_fall_back(status_code: int, html: str, extracted: str) -> bool:
    """Decide whether a curl_cffi response should trigger fallback to Playwright."""
    if status_code >= FALLBACK_STATUS_THRESHOLD:
        return True
    if _BOT_WALL_PATTERN.search(html[:BOT_WALL_SCAN_BYTES]):
        return True
    return len(extracted) < LOW_EXTRACTION_THRESHOLD and len(html) > HEAVY_HTML_THRESHOLD


async def _fetch_one(session: AsyncSession[Response], url: str) -> tuple[str, CurlFetchResult]:
    try:
        response: Response = await session.get(
            url,
            impersonate="chrome",
            timeout=CURL_TIMEOUT_SECONDS,
            allow_redirects=True,
        )
    except RequestException as exc:
        logger.debug("curl_cffi error url={!r} error={}", url, exc)
        return url, CurlFetchResult(text="", fall_back=True)
    html: str = response.text or ""
    extracted = trafilatura.extract(html) or ""
    text = (extracted or html)[:CONTENT_LIMIT]
    fall_back = should_fall_back(response.status_code, html, extracted)
    logger.debug(
        "curl_cffi url={!r} status={} chars={} fall_back={}",
        url,
        response.status_code,
        len(text),
        fall_back,
    )
    return url, CurlFetchResult(text=text, fall_back=fall_back)


@dataclass(frozen=True)
class CurlCffiPageFetcher:
    """Tier 0 fetcher: HTTP GET via curl_cffi with Chrome TLS impersonation."""

    async def fetch_pages(self, urls: list[str]) -> dict[str, CurlFetchResult]:
        """Fetch each URL concurrently and tag results with a ``fall_back`` flag."""
        if not urls:
            return {}
        async with AsyncSession[Response]() as session:
            results = await asyncio.gather(*[_fetch_one(session, u) for u in urls])
        return dict(results)

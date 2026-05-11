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
# Named only because ruff's PLR2004 forbids bare comparison literals; the
# values themselves are domain-obvious (HTTP error class, trafilatura minimum,
# "lots of HTML" threshold).
_FALLBACK_STATUS = 400
_LOW_EXTRACTION_CHARS = 200
_HEAVY_HTML_CHARS = 5000

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
    if status_code >= _FALLBACK_STATUS:
        return True
    # Scan the first 4 KB — bot-wall pages always declare themselves up top.
    if _BOT_WALL_PATTERN.search(html[:4096]):
        return True
    # Lots of HTML but no extracted article body → almost certainly a bot wall.
    return len(extracted) < _LOW_EXTRACTION_CHARS and len(html) > _HEAVY_HTML_CHARS


@dataclass(frozen=True)
class CurlCffiPageFetcher:
    """Tier 0 fetcher: HTTP GET via curl_cffi with Chrome TLS impersonation."""

    async def fetch_pages(self, urls: list[str]) -> dict[str, CurlFetchResult]:
        """Fetch each URL concurrently and tag results with a ``fall_back`` flag."""
        if not urls:
            return {}

        async with AsyncSession[Response]() as session:

            async def fetch_one(url: str) -> tuple[str, CurlFetchResult]:
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

            results = await asyncio.gather(*[fetch_one(u) for u in urls])

        return dict(results)

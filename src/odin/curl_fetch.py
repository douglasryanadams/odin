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

# Allowlist for response Content-Type. Anything else (PDF, image, archive,
# octet-stream, missing header) is rejected outright — Claude can only
# usefully consume prose, and binary payloads widen the prompt-injection
# surface without any upside.
ALLOWED_CONTENT_TYPES: frozenset[str] = frozenset(
    {"text/html", "text/plain", "application/xhtml+xml"}
)

# Ceiling on the raw response body, well above any legitimate text article
# and well below "the URL is serving us a binary blob in disguise". An
# advertised Content-Length above this discards the response before any
# extraction work; a server that omits the header still gets capped after
# read.
MAX_RESPONSE_BYTES = 2_000_000

_BOT_WALL_PATTERN = re.compile(
    r"just a moment|enable javascript|access denied|attention required|verify you are human",
    re.IGNORECASE,
)


def _content_type_allowed(header_value: str) -> bool:
    primary = header_value.split(";", 1)[0].strip().lower()
    return primary in ALLOWED_CONTENT_TYPES


def _content_length_oversized(header_value: str | None) -> bool:
    if not header_value:
        return False
    try:
        return int(header_value) > MAX_RESPONSE_BYTES
    except ValueError:
        return False


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
                if _content_length_oversized(response.headers.get("content-length")):
                    logger.debug(
                        "curl_cffi oversized url={!r} content_length={}",
                        url,
                        response.headers.get("content-length"),
                    )
                    return url, CurlFetchResult(text="", fall_back=False)
                if not _content_type_allowed(response.headers.get("content-type", "")):
                    logger.debug(
                        "curl_cffi disallowed content-type url={!r} content_type={!r}",
                        url,
                        response.headers.get("content-type", ""),
                    )
                    return url, CurlFetchResult(text="", fall_back=False)
                if len(response.content or b"") > MAX_RESPONSE_BYTES:
                    logger.debug(
                        "curl_cffi response body exceeded cap url={!r} bytes={}",
                        url,
                        len(response.content or b""),
                    )
                    return url, CurlFetchResult(text="", fall_back=False)
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

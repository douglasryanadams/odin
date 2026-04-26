"""Web page fetching and content extraction."""

import asyncio

import httpx
import trafilatura
from loguru import logger

CONTENT_LIMIT = 10_000


async def _fetch_one(client: httpx.AsyncClient, url: str) -> tuple[str, str]:
    try:
        response = await client.get(url, follow_redirects=True, timeout=10.0)
        response.raise_for_status()
        extracted = trafilatura.extract(response.text)
        text = extracted or response.text
        chars = min(len(text), CONTENT_LIMIT)
        logger.debug("fetch ok url={!r} chars={}", url, chars)
        return url, text[:CONTENT_LIMIT]
    except httpx.HTTPError as exc:
        logger.debug("fetch error url={!r} error={}", url, exc)
        return url, f"Error fetching URL: {exc}"


async def fetch_pages(urls: list[str]) -> dict[str, str]:
    """Fetch URLs in parallel, returning url -> extracted text."""
    async with httpx.AsyncClient() as client:
        results = await asyncio.gather(*[_fetch_one(client, url) for url in urls])
    return dict(results)

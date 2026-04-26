"""SearXNG search client."""

import httpx
from loguru import logger
from pydantic import BaseModel


class SearchResult(BaseModel):
    """A single search result from SearXNG."""

    url: str
    title: str
    content: str = ""
    engines: list[str] = []


async def search(query: str, base_url: str) -> list[SearchResult]:
    """Search SearXNG and return parsed results."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        logger.debug("fetching base_url={} query={!r}", base_url, query)
        response = await client.get(
            f"{base_url}/search",
            params={"q": query, "format": "json"},
            headers={"X-Forwarded-For": "127.0.0.1"},
        )
        response.raise_for_status()
        results = [SearchResult(**r) for r in response.json().get("results", [])]
        logger.debug("fetched results={}", len(results))
        return results

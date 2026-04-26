"""SearXNG search client."""

import httpx
from pydantic import BaseModel


class SearchResult(BaseModel):
    """A single search result from SearXNG."""

    url: str
    title: str
    content: str = ""


async def search(query: str, base_url: str) -> list[SearchResult]:
    """Search SearXNG and return parsed results."""
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{base_url}/search",
            params={"q": query, "format": "json"},
        )
        response.raise_for_status()
        return [SearchResult(**r) for r in response.json().get("results", [])]

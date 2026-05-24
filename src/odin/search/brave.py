"""Brave Search API as a SearchBackend: a first-party direct client.

Replaces reliance on SearXNG's braveapi engine. Maps Brave's web.results to the
neutral SearchResult, stamping engines=["brave"] so the aggregator can union
provenance across sources.
"""

import html
import re
from dataclasses import dataclass

import httpx
from loguru import logger

from odin.search.models import SearchResult

BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"
_BRAVE_RESULT_COUNT = 20  # matches the SearXNG braveapi engine's results_per_page
_TAG_RE = re.compile(r"<[^>]+>")


def _strip(snippet: str) -> str:
    """Reduce a Brave snippet (HTML with highlight tags) to plain text."""
    return html.unescape(_TAG_RE.sub("", snippet)).strip()


@dataclass(frozen=True)
class BraveBackend:
    """Query the Brave Search API directly and adapt it to the SearchBackend protocol."""

    api_key: str
    timeout_seconds: float = 30.0
    name: str = "brave"

    async def search(self, query: str) -> list[SearchResult]:
        """Run the query against Brave's web-search endpoint, mapping web.results."""
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            logger.debug("brave search query={!r}", query)
            response = await client.get(
                BRAVE_SEARCH_URL,
                params={"q": query, "count": _BRAVE_RESULT_COUNT},
                headers={"Accept": "application/json", "X-Subscription-Token": self.api_key},
            )
            response.raise_for_status()
            web = response.json().get("web", {})
            results = [
                SearchResult(
                    url=item["url"],
                    title=item.get("title", ""),
                    content=_strip(item.get("description", "")),
                    engines=["brave"],
                )
                for item in web.get("results", [])
            ]
            logger.debug("brave fetched results={}", len(results))
            return results

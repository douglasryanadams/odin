"""Wikipedia as a SearchBackend via the Wikimedia Core REST search endpoint.

SearXNG's bundled wikipedia engine is blocked from our cloud IPs because it sends
a ``searxng/<version>`` User-Agent that Wikimedia rejects. This first-party client
sends a policy-compliant User-Agent, which the endpoint serves unauthenticated,
and maps each result page to the neutral SearchResult.
"""

import html
import re
from dataclasses import dataclass

import httpx
from loguru import logger

from odin.search.models import SearchResult

_SEARCH_URL = "https://api.wikimedia.org/core/v1/wikipedia/en/search/page"
_DEFAULT_USER_AGENT = "Odin/1.0 (+https://odinseye.info; odin@odinseye.info) httpx"
_TAG_RE = re.compile(r"<[^>]+>")


def _strip_excerpt(excerpt: str) -> str:
    """Reduce a Wikimedia search excerpt (HTML with searchmatch spans) to plain text."""
    return html.unescape(_TAG_RE.sub("", excerpt)).strip()


@dataclass(frozen=True)
class WikipediaBackend:
    """Search English Wikipedia through the Wikimedia Core REST API.

    The endpoint serves search unauthenticated; a policy-compliant User-Agent is
    required, and is the one thing SearXNG's bundled engine could not provide.
    """

    user_agent: str = _DEFAULT_USER_AGENT
    limit: int = 10
    timeout_seconds: float = 30.0
    name: str = "wikipedia"

    async def search(self, query: str) -> list[SearchResult]:
        """Query the Wikimedia search endpoint and map each page to a SearchResult."""
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            logger.debug("wikipedia search query={!r}", query)
            response = await client.get(
                _SEARCH_URL,
                params={"q": query, "limit": self.limit},
                headers={"User-Agent": self.user_agent, "Accept": "application/json"},
            )
            response.raise_for_status()
            pages = response.json().get("pages", [])
            results = [
                SearchResult(
                    url=f"https://en.wikipedia.org/wiki/{page['key']}",
                    title=page["title"],
                    content=_strip_excerpt(page.get("excerpt", "")),
                    engines=["wikipedia"],
                )
                for page in pages
            ]
            logger.debug("wikipedia fetched results={}", len(results))
            return results

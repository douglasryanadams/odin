"""SearXNG as a SearchBackend: a thin adapter over :func:`odin.searxng.search`.

The SearXNG client itself stays in :mod:`odin.searxng`; this is only the seam
that lets it participate in the aggregator. Both are deleted together in the
final cut-over once first-party backends cover SearXNG's role.
"""

from dataclasses import dataclass

from odin import searxng
from odin.search.models import SearchResult


@dataclass(frozen=True)
class SearXngBackend:
    """Wrap the existing SearXNG JSON search behind the SearchBackend protocol."""

    base_url: str
    timeout_seconds: float = 30.0
    name: str = "searxng"

    async def search(self, query: str) -> list[SearchResult]:
        """Delegate to SearXNG, preserving its richer per-engine ``engines`` field."""
        return await searxng.search(query, self.base_url)

"""The SearchBackend protocol: the contract every search source implements."""

from typing import Protocol

from odin.search.models import SearchResult


class SearchBackend(Protocol):
    """A named, time-bounded async search source.

    ``name`` identifies the backend in result provenance (it is stamped into
    ``SearchResult.engines`` by first-party backends) and keys per-backend
    metrics. ``timeout_seconds`` is the per-call ceiling the aggregator enforces.
    Both are read-only properties so frozen-dataclass backends conform.
    """

    @property
    def name(self) -> str:
        """Stable identifier stamped into result provenance and metrics."""
        ...

    @property
    def timeout_seconds(self) -> float:
        """Per-call ceiling the aggregator enforces for this backend."""
        ...

    async def search(self, query: str) -> list[SearchResult]:
        """Run the query and return results, or raise on upstream failure.

        Backends raise on failure; the aggregator owns the decision to degrade.
        """
        ...

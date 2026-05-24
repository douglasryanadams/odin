"""First-party search layer.

Exposes the neutral :class:`SearchResult` model, the :class:`SearchBackend`
protocol, the :class:`SearchAggregator` that fans queries across backends, and
:func:`build_aggregator`, which assembles the enabled backend set from config.

Backends register through ``_REGISTRY``: each entry is a factory
``(settings) -> SearchBackend | None`` that returns ``None`` when its backend is
disabled or missing required config, so the aggregator is built fail-closed.
New backends add a factory here; the dependency wiring in ``app.py`` never changes.
"""

from collections.abc import Callable

from odin.config import Settings
from odin.search.aggregator import SearchAggregator, merge_results
from odin.search.base import SearchBackend
from odin.search.brave import BraveBackend
from odin.search.models import SearchResult
from odin.search.searxng_backend import SearXngBackend

__all__ = [
    "BraveBackend",
    "SearXngBackend",
    "SearchAggregator",
    "SearchBackend",
    "SearchResult",
    "build_aggregator",
    "merge_results",
]


def _searxng_factory(settings: Settings) -> SearchBackend | None:
    if not settings.searxng_enabled:
        return None
    return SearXngBackend(
        base_url=settings.searxng_url,
        timeout_seconds=settings.search_timeout_seconds,
    )


def _brave_factory(settings: Settings) -> SearchBackend | None:
    if not settings.brave_enabled or settings.brave_api_key is None:
        return None
    return BraveBackend(
        api_key=settings.brave_api_key,
        timeout_seconds=settings.search_timeout_seconds,
    )


_REGISTRY: tuple[Callable[[Settings], SearchBackend | None], ...] = (
    _searxng_factory,
    _brave_factory,
)


def build_aggregator(settings: Settings) -> SearchAggregator:
    """Instantiate every enabled backend from config and wrap them in an aggregator."""
    backends = tuple(backend for factory in _REGISTRY if (backend := factory(settings)) is not None)
    return SearchAggregator(backends=backends)

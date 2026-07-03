"""Fan a query across backends, merge by URL, and degrade gracefully.

The aggregation logic lives in module-level functions (:func:`gather_results`,
:func:`merge_results`) so it is testable without constructing a dataclass.
:class:`SearchAggregator` is only a thin :class:`SearchBackend` adapter that
holds the backend tuple and delegates.

The same merge rule is used in two places: across backends within a single
query (here) and across queries (in the pipeline). :func:`merge_results` is the
single source of that rule so the engines-union semantics stay identical at both
layers.
"""

import asyncio
import time
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import Literal

from loguru import logger

from odin.search.base import SearchBackend
from odin.search.models import SearchResult


@dataclass(frozen=True)
class BackendOutcome:
    """What happened when one backend was queried: outcome, timing, and yield."""

    name: str
    elapsed_seconds: float
    outcome: Literal["success", "timeout", "error"]
    result_count: int


MetricsRecorder = Callable[[BackendOutcome], Awaitable[None]]


async def _no_op_recorder(outcome: BackendOutcome) -> None:
    """Discard the outcome, so callers that don't care about metrics need not pass one."""


def merge_results(batches: Iterable[Iterable[SearchResult]]) -> list[SearchResult]:
    """Dedupe results by URL, preserving first-seen order and unioning engines.

    On a URL collision the first result keeps its position; the later result's
    ``engines`` are unioned in (order-preserving, deduped) and any empty title
    or content is backfilled from it.
    """
    merged: dict[str, SearchResult] = {}
    for batch in batches:
        for result in batch:
            existing = merged.get(result.url)
            if existing is None:
                merged[result.url] = result
                continue
            engines = list(existing.engines)
            for engine in result.engines:
                if engine not in engines:
                    engines.append(engine)
            merged[result.url] = existing.model_copy(
                update={
                    "engines": engines,
                    "title": existing.title or result.title,
                    "content": existing.content or result.content,
                }
            )
    return list(merged.values())


async def _guarded(
    backend: SearchBackend, query: str, record_outcome: MetricsRecorder
) -> list[SearchResult]:
    """Run one backend under its timeout, returning [] on timeout or error.

    Always reports what happened to ``record_outcome``, win or lose, so
    per-backend metrics stay complete rather than only covering failures.
    """
    start = time.monotonic()
    try:
        async with asyncio.timeout(backend.timeout_seconds):
            results = await backend.search(query)
    except TimeoutError:
        logger.warning(
            "search backend timed out name={} timeout={}",
            backend.name,
            backend.timeout_seconds,
        )
        await record_outcome(
            BackendOutcome(
                name=backend.name,
                elapsed_seconds=time.monotonic() - start,
                outcome="timeout",
                result_count=0,
            )
        )
        return []
    except Exception as exc:  # noqa: BLE001 — one backend must not sink the query
        logger.warning("search backend failed name={} error={}", backend.name, exc)
        await record_outcome(
            BackendOutcome(
                name=backend.name,
                elapsed_seconds=time.monotonic() - start,
                outcome="error",
                result_count=0,
            )
        )
        return []
    await record_outcome(
        BackendOutcome(
            name=backend.name,
            elapsed_seconds=time.monotonic() - start,
            outcome="success",
            result_count=len(results),
        )
    )
    return results


async def gather_results(
    backends: tuple[SearchBackend, ...],
    query: str,
    record_outcome: MetricsRecorder = _no_op_recorder,
) -> list[SearchResult]:
    """Query every backend concurrently under per-backend timeouts and merge.

    A backend that times out or raises contributes no results rather than
    sinking the query (partial results allowed). With no backends, or when all
    fail, the result is an empty list, never an exception.
    """
    if not backends:
        return []
    batches = await asyncio.gather(
        *[_guarded(backend, query, record_outcome) for backend in backends]
    )
    return merge_results(batches)


@dataclass(frozen=True)
class SearchAggregator:
    """A :class:`SearchBackend` over several backends.

    Holds the backend tuple and delegates to :func:`gather_results`; satisfying
    the protocol lets the pipeline treat one backend, several, or a test double
    interchangeably.
    """

    backends: tuple[SearchBackend, ...]
    name: str = "aggregator"
    timeout_seconds: float = 30.0
    record_outcome: MetricsRecorder = _no_op_recorder

    async def search(self, query: str) -> list[SearchResult]:
        """Query all backends concurrently and return their merged results."""
        return await gather_results(self.backends, query, self.record_outcome)

"""Profile pipeline orchestrator."""

import asyncio
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any, cast

from anthropic import AsyncAnthropic, BadRequestError, RateLimitError
from loguru import logger

from odin import claude, fetch, url_filter
from odin.config import settings
from odin.models import CategorizeResult, Category
from odin.search import SearchAggregator, SearchBackend, SearchResult, merge_results

SEARCH_QUERY_CONCURRENCY = 2
DEEP_MODE_MAX_ROUNDS = 2
_CONNECTION_MIN_SOURCES = 2

SERVICE_UNAVAILABLE_MESSAGE = "Odin is temporarily paused. Please try again in a little while."
_NO_SOURCES_MESSAGE = "No usable sources were found for this query. Please try rephrasing."


def is_billing_error(exc: BadRequestError) -> bool:
    """Return True when the error body indicates an Anthropic billing cap."""
    body = getattr(exc, "body", None)
    if not isinstance(body, dict):
        return False
    error = cast("dict[str, Any]", body).get("error")
    if not isinstance(error, dict):
        return False
    return cast("dict[str, Any]", error).get("type") == "billing_error"


def _missing_backend_names(
    results: list[SearchResult], backends: tuple[SearchBackend, ...]
) -> list[str]:
    """Name configured backends absent from the merged results' provenance.

    A backend can contribute nothing for many reasons — error, timeout, or
    genuinely nothing relevant — and the aggregator does not distinguish them
    (see _guarded). Naming the backend states only the fact a reader cares
    about: which sources did not shape this profile.
    """
    contributed = {engine for result in results for engine in result.engines}
    return [backend.name for backend in backends if backend.name not in contributed]


@dataclass
class StageEvent:
    """A pipeline progress event yielded by build_profile."""

    stage: str
    data: dict[str, Any]


async def _run_with_degraded_errors(
    pipeline: AsyncGenerator[StageEvent, None],
) -> AsyncGenerator[StageEvent, None]:
    """Run a pipeline generator, turning Anthropic capacity errors into a degraded event.

    A rate limit or billing cap means Odin itself is temporarily unable to
    serve, not that this particular query failed — both fast and deep
    pipelines surface that the same way, as a `service_unavailable` event
    rather than a stack trace.
    """
    try:
        async for event in pipeline:
            yield event
    except RateLimitError as exc:
        logger.warning("anthropic rate-limited: {}", exc)
        yield StageEvent(stage="service_unavailable", data={"message": SERVICE_UNAVAILABLE_MESSAGE})
    except BadRequestError as exc:
        if not is_billing_error(exc):
            raise
        logger.warning("anthropic billing limit reached: {}", exc)
        yield StageEvent(stage="service_unavailable", data={"message": SERVICE_UNAVAILABLE_MESSAGE})


async def build_profile(
    query: str,
    searcher: SearchAggregator,
    anthropic_client: AsyncAnthropic,
    fetcher: fetch.PageFetcher,
    *,
    pre_categorized: CategorizeResult | None = None,
) -> AsyncGenerator[StageEvent, None]:
    """Run the profile pipeline, yielding a StageEvent at each step."""
    logger.debug("pipeline start query={!r}", query)
    async for event in _run_with_degraded_errors(
        _run_pipeline(query, searcher, anthropic_client, fetcher, pre_categorized=pre_categorized)
    ):
        yield event


async def build_deep_profile(
    query: str,
    searcher: SearchAggregator,
    anthropic_client: AsyncAnthropic,
    fetcher: fetch.PageFetcher,
    *,
    pre_categorized: CategorizeResult | None = None,
) -> AsyncGenerator[StageEvent, None]:
    """Run the deep-research pipeline: an initial pass plus bounded follow-up rounds.

    Same degraded-error handling as `build_profile` — the only difference is
    which orchestration runs underneath.
    """
    logger.debug("deep pipeline start query={!r}", query)
    async for event in _run_with_degraded_errors(
        _run_deep_pipeline(
            query, searcher, anthropic_client, fetcher, pre_categorized=pre_categorized
        )
    ):
        yield event


async def _gather_search_results(queries: list[str], searcher: SearchBackend) -> list[SearchResult]:
    """Search for every query with bounded concurrency, then merge duplicate URLs.

    Caps in-flight backend.search calls at SEARCH_QUERY_CONCURRENCY so a long
    query list can't overwhelm the search backend, then hands the per-query
    batches to merge_results to dedupe by URL and union engines.
    """
    semaphore = asyncio.Semaphore(SEARCH_QUERY_CONCURRENCY)

    async def _throttled_search(q: str) -> list[SearchResult]:
        async with semaphore:
            return await searcher.search(q)

    results_per_query = await asyncio.gather(*[_throttled_search(q) for q in queries])
    return merge_results(results_per_query)


async def _run_search_and_filter(
    queries: list[str], searcher: SearchAggregator
) -> tuple[list[SearchResult], list[str]]:
    """Search for queries, filter blocked URLs, and log what was dropped or missing.

    Returns (allowed_results, missing_backend_names).
    """
    unique_results = await _gather_search_results(queries, searcher)
    allowed_results = url_filter.filter_search_results(
        unique_results, blocked_domains=settings.url_domain_blocklist
    )
    dropped = len(unique_results) - len(allowed_results)
    if dropped:
        logger.debug("url_filter dropped count={} kept={}", dropped, len(allowed_results))
    logger.debug("search complete unique_results={}", len(allowed_results))
    missing_backends = _missing_backend_names(unique_results, searcher.backends)
    if missing_backends:
        logger.debug("backends contributed nothing names={}", missing_backends)
    return allowed_results, missing_backends


async def _run_pipeline(
    query: str,
    searcher: SearchAggregator,
    anthropic_client: AsyncAnthropic,
    fetcher: fetch.PageFetcher,
    *,
    pre_categorized: CategorizeResult | None = None,
) -> AsyncGenerator[StageEvent, None]:
    if pre_categorized is None:
        pre_categorized = await claude.categorize(anthropic_client, query)
    category = pre_categorized.category
    logger.debug("categorized category={}", category)
    yield StageEvent(stage="categorized", data={"category": category})

    queries = await claude.generate_queries(anthropic_client, query, category)
    logger.debug("queries generated count={}", len(queries))
    yield StageEvent(stage="queries", data={"queries": queries})

    allowed_results, missing_backends = await _run_search_and_filter(queries, searcher)
    yield StageEvent(
        stage="searching",
        data={"result_count": len(allowed_results), "missing_backends": missing_backends},
    )

    selected_urls = await claude.select_urls(anthropic_client, query, allowed_results)
    logger.debug("urls selected count={}", len(selected_urls))
    yield StageEvent(stage="fetching", data={"url_count": len(selected_urls)})

    content = await fetcher.fetch_pages(selected_urls)
    logger.debug("pages fetched count={}", len(content))

    async for event in _finish_pipeline(
        query, category, content, allowed_results, anthropic_client
    ):
        yield event


def _all_pages_empty(content: dict[str, str]) -> bool:
    """Report whether every fetched page came back blank, so callers can refuse to synthesize."""
    return not any(text.strip() for text in content.values())


async def _finish_pipeline(
    query: str,
    category: Category,
    content: dict[str, str],
    sources: list[SearchResult],
    anthropic_client: AsyncAnthropic,
) -> AsyncGenerator[StageEvent, None]:
    """Run the shared tail both pipelines end with: synthesize and assess together.

    Guards against empty content, then builds the final profile and audits it in
    one Sonnet call. The assessment is non-essential: when Claude returns no
    audit the profile still ships, just without an `assessment` event. Identical
    for fast and deep modes — the deep pipeline's extra rounds only change what
    `content`/`sources` contain by the time this runs.
    """
    if _all_pages_empty(content):
        logger.warning("all fetched pages empty, refusing to synthesize query={!r}", query)
        yield StageEvent(stage="service_unavailable", data={"message": _NO_SOURCES_MESSAGE})
        return
    yield StageEvent(stage="synthesizing", data={"page_count": len(content)})

    profile, assessment = await claude.synthesize_and_assess(
        anthropic_client, query, category, content, sources
    )
    logger.debug("profile synthesized name={!r} citations={}", profile.name, len(profile.citations))
    yield StageEvent(stage="profile", data=profile.model_dump())

    if assessment is None:
        logger.warning("assessment absent; skipping assessment event query={!r}", query)
        return
    logger.debug("assessment ready caveats={}", len(assessment.caveats))
    yield StageEvent(stage="assessment", data=assessment.model_dump())


@dataclass
class _ResearchState:
    """Mutable accumulator the follow-up round loop updates in place.

    Mirrors the pass-a-mutable-collection-and-update-it shape
    routes/profile.py::_stream_pipeline already uses for `collected` — each
    successful round merges its new sources and content into the running set
    the final synthesis sees.
    """

    sources: list[SearchResult]
    content: dict[str, str]


async def _run_followup_rounds(  # noqa: PLR0913 — bundling searcher/anthropic_client/fetcher would obscure the round shape
    query: str,
    gap_queries: list[tuple[str, str]],
    state: _ResearchState,
    searcher: SearchAggregator,
    anthropic_client: AsyncAnthropic,
    fetcher: fetch.PageFetcher,
) -> AsyncGenerator[StageEvent, None]:
    """Run one bounded round of search, select, and fetch per gap query.

    Sliced to DEEP_MODE_MAX_ROUNDS regardless of how many queries identify_gaps
    returns — the tool schema already caps it, but the loop does not rely on
    that alone to bound cost. Each round dedupes its candidates against
    `state.content` before spending a select_urls call and again before
    fetching, and is skipped silently — no events, no extra calls — when
    nothing new survives either check, so a round that can't add anything
    doesn't cost anything either.
    """
    for round_number, (gap_query, gap_reason) in enumerate(
        gap_queries[:DEEP_MODE_MAX_ROUNDS], start=1
    ):
        results = await searcher.search(gap_query)
        allowed_results = url_filter.filter_search_results(
            results, blocked_domains=settings.url_domain_blocklist
        )
        new_results = [result for result in allowed_results if result.url not in state.content]
        if not new_results:
            logger.debug(
                "deep round {} query={!r} found nothing new, skipping", round_number, gap_query
            )
            continue
        yield StageEvent(
            stage="deep_searching",
            data={
                "round": round_number,
                "query": gap_query,
                "reason": gap_reason,
                "result_count": len(new_results),
            },
        )

        selected_urls = await claude.select_urls(anthropic_client, query, new_results)
        new_urls = [url for url in selected_urls if url not in state.content]
        if not new_urls:
            logger.debug(
                "deep round {} query={!r} selected nothing new, skipping fetch",
                round_number,
                gap_query,
            )
            continue
        yield StageEvent(
            stage="deep_fetching",
            data={
                "round": round_number,
                "query": gap_query,
                "reason": gap_reason,
                "url_count": len(new_urls),
            },
        )

        new_content = await fetcher.fetch_pages(new_urls)
        logger.debug(
            "deep round {} query={!r} fetched count={}", round_number, gap_query, len(new_content)
        )
        state.sources = merge_results([state.sources, new_results])
        state.content = {**state.content, **new_content}


async def _run_connection_pass(
    query: str,
    category: Category,
    sources: list[SearchResult],
    content: dict[str, str],
    anthropic_client: AsyncAnthropic,
) -> AsyncGenerator[StageEvent, None]:
    """Look for corroboration, contradiction, and links across the gathered pages.

    Runs once on the full merged set the follow-up rounds produced — never
    per round, so this adds exactly one bounded Sonnet call to deep mode's
    fixed cost regardless of how many rounds ran. Gated on `content` rather
    than `sources`: `state.sources` carries every search result that survived
    the URL filter (provenance for citation lookup), but `find_connections`
    compares fetched *page text* against itself, and only a fraction of those
    sources ever get fetched. Skipped silently below two fetched pages —
    "cross-source" is meaningless with one, and spending a call to confirm
    that would cost without ever returning anything, the same
    cost-consciousness `_run_followup_rounds` already applies per round.
    `claude.find_connections` does the actual grounding — every connection it
    returns has already resolved to two distinct cited sources.
    """
    if len(content) < _CONNECTION_MIN_SOURCES:
        logger.debug("connection pass skipped, only {} page(s) fetched", len(content))
        return
    yield StageEvent(stage="deep_connecting", data={"source_count": len(content)})
    connections = await claude.find_connections(anthropic_client, query, category, content, sources)
    logger.debug("connections found count={}", len(connections))
    yield StageEvent(
        stage="connections", data={"connections": [c.model_dump() for c in connections]}
    )


async def _run_deep_pipeline(
    query: str,
    searcher: SearchAggregator,
    anthropic_client: AsyncAnthropic,
    fetcher: fetch.PageFetcher,
    *,
    pre_categorized: CategorizeResult | None = None,
) -> AsyncGenerator[StageEvent, None]:
    """Run an initial pass, draft and analyze it for gaps, then run bounded follow-up rounds.

    The initial pass mirrors `_run_pipeline`'s exactly — kept as its own copy
    rather than shared, since deep mode's first pass may reasonably diverge
    later (e.g. fewer initial queries to leave room for follow-ups). After the
    first fetch, a draft synthesis gives `identify_gaps` a structured signal
    to spot real coverage gaps from, rather than guessing off raw snippets.
    The draft is deliberately never yielded as a `profile` event — the
    renderer treats that as *the* answer, and surfacing an interim one would
    need new frontend machinery to "upgrade" it later, which is slice 3's job.
    """
    if pre_categorized is None:
        pre_categorized = await claude.categorize(anthropic_client, query)
    category = pre_categorized.category
    logger.debug("categorized category={}", category)
    yield StageEvent(stage="categorized", data={"category": category})

    queries = await claude.generate_queries(anthropic_client, query, category)
    logger.debug("queries generated count={}", len(queries))
    yield StageEvent(stage="queries", data={"queries": queries})

    allowed_results, missing_backends = await _run_search_and_filter(queries, searcher)
    yield StageEvent(
        stage="searching",
        data={"result_count": len(allowed_results), "missing_backends": missing_backends},
    )

    selected_urls = await claude.select_urls(anthropic_client, query, allowed_results)
    logger.debug("urls selected count={}", len(selected_urls))
    yield StageEvent(stage="fetching", data={"url_count": len(selected_urls)})

    content = await fetcher.fetch_pages(selected_urls)
    logger.debug("pages fetched count={}", len(content))
    if _all_pages_empty(content):
        logger.warning("all fetched pages empty, refusing to synthesize query={!r}", query)
        yield StageEvent(stage="service_unavailable", data={"message": _NO_SOURCES_MESSAGE})
        return

    yield StageEvent(stage="draft_synthesizing", data={"page_count": len(content)})
    draft = await claude.synthesize(anthropic_client, query, category, content, allowed_results)
    logger.debug("draft profile synthesized name={!r}", draft.name)

    gap_pairs = await claude.identify_gaps(anthropic_client, query, category, draft)
    logger.debug("gap analysis pairs={}", gap_pairs)
    yield StageEvent(
        stage="deep_gap_analysis",
        data={
            "queries": [q for q, _ in gap_pairs],
            "reasons": [r for _, r in gap_pairs],
        },
    )

    state = _ResearchState(sources=list(allowed_results), content=dict(content))
    if gap_pairs:
        async for event in _run_followup_rounds(
            query, gap_pairs, state, searcher, anthropic_client, fetcher
        ):
            yield event

    async for event in _run_connection_pass(
        query, category, state.sources, state.content, anthropic_client
    ):
        yield event

    async for event in _finish_pipeline(
        query, category, state.content, state.sources, anthropic_client
    ):
        yield event

"""Profile pipeline orchestrator."""

import asyncio
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any, cast

from anthropic import AsyncAnthropic, BadRequestError, RateLimitError
from loguru import logger

from odin import claude, fetch, url_filter
from odin.config import settings
from odin.search import SearchAggregator, SearchBackend, SearchResult, merge_results

SEARCH_QUERY_CONCURRENCY = 2

_SERVICE_UNAVAILABLE_MESSAGE = "Odin is temporarily paused. Please try again in a little while."
_NO_SOURCES_MESSAGE = "No usable sources were found for this query. Please try rephrasing."


def _is_billing_error(exc: BadRequestError) -> bool:
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


async def build_profile(
    query: str,
    searcher: SearchAggregator,
    anthropic_client: AsyncAnthropic,
    fetcher: fetch.PageFetcher,
) -> AsyncGenerator[StageEvent, None]:
    """Run the profile pipeline, yielding a StageEvent at each step."""
    logger.debug("pipeline start query={!r}", query)

    try:
        async for event in _run_pipeline(query, searcher, anthropic_client, fetcher):
            yield event
    except RateLimitError as exc:
        logger.warning("anthropic rate-limited: {}", exc)
        yield StageEvent(
            stage="service_unavailable", data={"message": _SERVICE_UNAVAILABLE_MESSAGE}
        )
    except BadRequestError as exc:
        if not _is_billing_error(exc):
            raise
        logger.warning("anthropic billing limit reached: {}", exc)
        yield StageEvent(
            stage="service_unavailable", data={"message": _SERVICE_UNAVAILABLE_MESSAGE}
        )


async def _run_pipeline(
    query: str,
    searcher: SearchAggregator,
    anthropic_client: AsyncAnthropic,
    fetcher: fetch.PageFetcher,
) -> AsyncGenerator[StageEvent, None]:
    category = await claude.categorize(anthropic_client, query)
    logger.debug("categorized category={}", category)
    yield StageEvent(stage="categorized", data={"category": category})

    queries = await claude.generate_queries(anthropic_client, query, category)
    logger.debug("queries generated count={}", len(queries))
    yield StageEvent(stage="queries", data={"queries": queries})

    semaphore = asyncio.Semaphore(SEARCH_QUERY_CONCURRENCY)

    async def _throttled_search(q: str) -> list[SearchResult]:
        async with semaphore:
            return await searcher.search(q)

    results_per_query = await asyncio.gather(*[_throttled_search(q) for q in queries])
    unique_results = merge_results(results_per_query)
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
    yield StageEvent(
        stage="searching",
        data={"result_count": len(allowed_results), "missing_backends": missing_backends},
    )

    selected_urls = await claude.select_urls(anthropic_client, query, allowed_results)
    logger.debug("urls selected count={}", len(selected_urls))
    yield StageEvent(stage="fetching", data={"url_count": len(selected_urls)})

    content = await fetcher.fetch_pages(selected_urls)
    logger.debug("pages fetched count={}", len(content))
    if not any(text.strip() for text in content.values()):
        logger.warning("all fetched pages empty, refusing to synthesize query={!r}", query)
        yield StageEvent(stage="service_unavailable", data={"message": _NO_SOURCES_MESSAGE})
        return
    yield StageEvent(stage="synthesizing", data={"page_count": len(content)})

    profile = await claude.synthesize(anthropic_client, query, category, content, allowed_results)
    logger.debug("profile synthesized name={!r} citations={}", profile.name, len(profile.citations))
    yield StageEvent(stage="profile", data=profile.model_dump())

    yield StageEvent(stage="assessing", data={})
    try:
        assessment = await claude.assess(anthropic_client, query, profile, content)
    except (RateLimitError, BadRequestError):
        raise
    except Exception as exc:  # noqa: BLE001 — assess is non-essential; degrade gracefully
        logger.warning("assess failed; skipping assessment event: {}", exc)
        return
    logger.debug("assessment ready caveats={}", len(assessment.caveats))
    yield StageEvent(stage="assessment", data=assessment.model_dump())

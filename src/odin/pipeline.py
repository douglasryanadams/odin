"""Profile pipeline orchestrator."""

import asyncio
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any, cast

from anthropic import AsyncAnthropic, BadRequestError, RateLimitError
from loguru import logger

from odin import claude, fetch, searxng

SEARXNG_MAX_CONCURRENCY = 2

_SERVICE_UNAVAILABLE_MESSAGE = "Odin is temporarily paused. Please try again in a little while."


def _is_billing_error(exc: BadRequestError) -> bool:
    body = getattr(exc, "body", None)
    if not isinstance(body, dict):
        return False
    error = cast("dict[str, Any]", body).get("error")
    if not isinstance(error, dict):
        return False
    return cast("dict[str, Any]", error).get("type") == "billing_error"


@dataclass
class StageEvent:
    """A pipeline progress event yielded by build_profile."""

    stage: str
    data: dict[str, Any]


async def build_profile(
    query: str,
    searxng_url: str,
    anthropic_client: AsyncAnthropic,
    fetcher: fetch.PageFetcher,
) -> AsyncGenerator[StageEvent, None]:
    """Run the profile pipeline, yielding a StageEvent at each step."""
    logger.debug("pipeline start query={!r}", query)

    try:
        async for event in _run_pipeline(query, searxng_url, anthropic_client, fetcher):
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
    searxng_url: str,
    anthropic_client: AsyncAnthropic,
    fetcher: fetch.PageFetcher,
) -> AsyncGenerator[StageEvent, None]:
    category = await claude.categorize(anthropic_client, query)
    logger.debug("categorized category={}", category)
    yield StageEvent(stage="categorized", data={"category": category})

    queries = await claude.generate_queries(anthropic_client, query, category)
    logger.debug("queries generated count={}", len(queries))
    yield StageEvent(stage="queries", data={"queries": queries})

    semaphore = asyncio.Semaphore(SEARXNG_MAX_CONCURRENCY)

    async def _throttled_search(q: str) -> list[searxng.SearchResult]:
        async with semaphore:
            return await searxng.search(q, searxng_url)

    results_per_query = await asyncio.gather(*[_throttled_search(q) for q in queries])
    seen: set[str] = set()
    unique_results: list[searxng.SearchResult] = []
    for batch in results_per_query:
        for r in batch:
            if r.url not in seen:
                seen.add(r.url)
                unique_results.append(r)
    logger.debug("search complete unique_results={}", len(unique_results))
    yield StageEvent(stage="searching", data={"result_count": len(unique_results)})

    selected_urls = await claude.select_urls(anthropic_client, query, unique_results)
    logger.debug("urls selected count={}", len(selected_urls))
    yield StageEvent(stage="fetching", data={"url_count": len(selected_urls)})

    content = await fetcher.fetch_pages(selected_urls)
    logger.debug("pages fetched count={}", len(content))
    yield StageEvent(stage="synthesizing", data={"page_count": len(content)})

    profile = await claude.synthesize(anthropic_client, query, category, content, unique_results)
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
    logger.debug(
        "assessment ready confidence={} caveats={}", assessment.confidence, len(assessment.caveats)
    )
    yield StageEvent(stage="assessment", data=assessment.model_dump())

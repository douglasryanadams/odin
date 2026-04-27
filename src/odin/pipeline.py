"""Profile pipeline orchestrator."""

import asyncio
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any

from anthropic import AsyncAnthropic
from loguru import logger

from odin import claude, fetch, searxng

SEARXNG_MAX_CONCURRENCY = 2


@dataclass
class StageEvent:
    """A pipeline progress event yielded by build_profile."""

    stage: str
    data: dict[str, Any]


async def build_profile(
    query: str,
    searxng_url: str,
    anthropic_client: AsyncAnthropic,
) -> AsyncGenerator[StageEvent, None]:
    """Run the profile pipeline, yielding a StageEvent at each step."""
    logger.debug("pipeline start query={!r}", query)

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

    content = await fetch.fetch_pages(selected_urls)
    logger.debug("pages fetched count={}", len(content))
    profile = await claude.synthesize(anthropic_client, query, category, content, unique_results)
    logger.debug("profile synthesized name={!r} citations={}", profile.name, len(profile.citations))
    yield StageEvent(stage="profile", data=profile.model_dump())

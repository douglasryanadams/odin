"""Profile pipeline orchestrator."""

import asyncio
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any

from anthropic import AsyncAnthropic

from odin import claude, fetch, searxng


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
    category = await claude.categorize(anthropic_client, query)
    yield StageEvent(stage="categorized", data={"category": category})

    queries = await claude.generate_queries(anthropic_client, query, category)
    yield StageEvent(stage="queries", data={"queries": queries})

    results_per_query = await asyncio.gather(*[searxng.search(q, searxng_url) for q in queries])
    seen: set[str] = set()
    unique_results: list[searxng.SearchResult] = []
    for batch in results_per_query:
        for r in batch:
            if r.url not in seen:
                seen.add(r.url)
                unique_results.append(r)
    yield StageEvent(stage="searching", data={"result_count": len(unique_results)})

    selected_urls = await claude.select_urls(anthropic_client, query, unique_results)
    yield StageEvent(stage="fetching", data={"url_count": len(selected_urls)})

    content = await fetch.fetch_pages(selected_urls)
    profile = await claude.synthesize(anthropic_client, query, category, content)
    yield StageEvent(stage="profile", data=profile.model_dump())

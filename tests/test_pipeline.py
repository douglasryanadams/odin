"""Tests for the profile pipeline."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from odin import pipeline
from odin.searxng import SearchResult


async def test_pipeline_bounds_searxng_concurrency() -> None:
    """build_profile should cap in-flight searxng.search calls at SEARXNG_MAX_CONCURRENCY."""
    inflight = 0
    max_inflight = 0

    async def fake_search(q: str, base_url: str) -> list[SearchResult]:  # noqa: ARG001
        nonlocal inflight, max_inflight
        inflight += 1
        max_inflight = max(max_inflight, inflight)
        await asyncio.sleep(0.05)
        inflight -= 1
        return [SearchResult(url=f"https://e/{q}", title=q, content="", engines=["x"])]

    queries = [f"q{i}" for i in range(6)]
    anthropic = MagicMock()
    profile = MagicMock()
    profile.name = "n"

    with (
        patch.object(pipeline.claude, "categorize", AsyncMock(return_value="other")),
        patch.object(pipeline.claude, "generate_queries", AsyncMock(return_value=queries)),
        patch.object(pipeline.claude, "select_urls", AsyncMock(return_value=[])),
        patch.object(pipeline.claude, "synthesize", AsyncMock(return_value=profile)),
        patch.object(pipeline.fetch, "fetch_pages", AsyncMock(return_value=[])),
        patch.object(pipeline.searxng, "search", side_effect=fake_search),
    ):
        async for _ in pipeline.build_profile("foo", "http://test", anthropic):
            pass

    assert max_inflight <= pipeline.SEARXNG_MAX_CONCURRENCY
    assert max_inflight >= 2, "sanity: the test should actually exercise concurrency"

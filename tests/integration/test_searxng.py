"""Integration tests for direct SearXNG search behavior."""

import asyncio

import pytest

from odin.searxng import search

SEARXNG_URL = "http://searxng:8080"


@pytest.mark.integration
def test_search_returns_results_from_multiple_engines() -> None:
    """Search results should come from at least 3 distinct engines."""
    results = asyncio.run(search("python programming language", SEARXNG_URL))
    assert len(results) > 0
    all_engines = {engine for result in results for engine in result.engines}
    assert len(all_engines) >= 3, f"Expected >= 3 engines, got: {all_engines}"

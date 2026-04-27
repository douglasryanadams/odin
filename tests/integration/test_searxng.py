"""Integration tests for direct SearXNG search behavior."""

import asyncio

import pytest

from odin.searxng import search

SEARXNG_URL = "http://searxng:8080"


@pytest.mark.integration
def test_search_returns_results() -> None:
    """End-to-end search call against the real SearXNG container returns results."""
    results = asyncio.run(search("python programming language", SEARXNG_URL))
    assert len(results) > 0

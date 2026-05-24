"""Integration test for the first-party Wikipedia search backend.

No credentials required: the Wikimedia Core REST search endpoint serves
unauthenticated given a policy-compliant User-Agent.
"""

import asyncio

import pytest

from odin.search.wikipedia import WikipediaBackend


@pytest.mark.integration
def test_wikipedia_backend_returns_results_for_a_real_query() -> None:
    """Wikimedia's search endpoint returns at least one well-formed page."""
    backend = WikipediaBackend()
    results = asyncio.run(backend.search("Marie Curie"))

    assert len(results) > 0
    for r in results:
        assert r.url.startswith("https://en.wikipedia.org/wiki/")
        assert r.title
        assert r.engines == ["wikipedia"]

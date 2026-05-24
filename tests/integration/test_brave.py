"""Integration test for the direct Brave Search API backend.

Skips when BRAVE_API_KEY is unset or the CI dummy ("ci-dummy") so `make test`
passes for developers without a Brave subscription; opt in by exporting a real
key (or putting it in `.env`).
"""

import asyncio

import pytest

from odin.config import settings
from odin.search.brave import BraveBackend


@pytest.mark.integration
def test_brave_backend_returns_results_for_a_real_query() -> None:
    """Brave's web-search endpoint returns at least one well-formed result."""
    key = settings.brave_api_key
    if not key or key == "ci-dummy":
        pytest.skip(
            "BRAVE_API_KEY is unset (or the ci-dummy placeholder). "
            "Set a real key from https://api-dashboard.search.brave.com/ in .env to opt in."
        )

    backend = BraveBackend(api_key=key)
    results = asyncio.run(backend.search("python programming language"))

    assert len(results) > 0
    for r in results:
        assert r.url.startswith(("http://", "https://"))
        assert r.title
        assert r.engines == ["brave"]

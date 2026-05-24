"""Contract tests for individual search backends."""

from unittest.mock import AsyncMock, patch

from odin.search import SearchResult
from odin.search.searxng_backend import SearXngBackend


async def test_searxng_backend_delegates_to_searxng_search() -> None:
    """SearXngBackend.search forwards to searxng.search with its base_url, returning the results."""
    expected = [SearchResult(url="https://x/1", title="t", content="c", engines=["brave"])]
    backend = SearXngBackend(base_url="http://searxng:8080")
    with patch(
        "odin.search.searxng_backend.searxng.search", AsyncMock(return_value=expected)
    ) as mock:
        out = await backend.search("marie curie")
    mock.assert_awaited_once_with("marie curie", "http://searxng:8080")
    assert out == expected

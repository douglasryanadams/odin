"""Contract tests for individual search backends."""

from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx

from odin.search import SearchResult
from odin.search.brave import BRAVE_SEARCH_URL, BraveBackend
from odin.search.searxng_backend import SearXngBackend

_BRAVE_KEY = "test-subscription-token"

_BRAVE_RESPONSE: dict[str, Any] = {
    "web": {
        "results": [
            {
                "url": "https://en.wikipedia.org/wiki/Marie_Curie",
                "title": "Marie Curie",
                "description": "Polish-French <strong>physicist</strong> &amp; chemist.",
            },
            {
                "url": "https://www.nobelprize.org/marie-curie",
            },
        ]
    }
}

_BRAVE_EMPTY_RESPONSE: dict[str, Any] = {"web": {"results": []}}


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


async def test_brave_backend_maps_web_results_to_search_results() -> None:
    """BraveBackend maps web.results to SearchResult, stamping engines=["brave"] on each."""
    backend = BraveBackend(api_key=_BRAVE_KEY)
    with respx.mock:
        respx.get(BRAVE_SEARCH_URL).mock(return_value=httpx.Response(200, json=_BRAVE_RESPONSE))
        out = await backend.search("marie curie")

    assert [r.url for r in out] == [
        "https://en.wikipedia.org/wiki/Marie_Curie",
        "https://www.nobelprize.org/marie-curie",
    ]
    assert out[0].title == "Marie Curie"
    assert all(r.engines == ["brave"] for r in out)


async def test_brave_backend_strips_html_and_entities_from_snippets() -> None:
    """Brave descriptions arrive as HTML with highlight tags; the backend yields plain text."""
    backend = BraveBackend(api_key=_BRAVE_KEY)
    with respx.mock:
        respx.get(BRAVE_SEARCH_URL).mock(return_value=httpx.Response(200, json=_BRAVE_RESPONSE))
        out = await backend.search("marie curie")

    content = out[0].content
    assert "<strong>" not in content
    assert "<" not in content
    assert "physicist & chemist" in content


async def test_brave_backend_empty_results_returns_empty_list() -> None:
    """An empty web.results array maps to an empty list, not an error."""
    backend = BraveBackend(api_key=_BRAVE_KEY)
    with respx.mock:
        respx.get(BRAVE_SEARCH_URL).mock(
            return_value=httpx.Response(200, json=_BRAVE_EMPTY_RESPONSE)
        )
        out = await backend.search("no such subject")

    assert out == []


async def test_brave_backend_raises_on_http_error() -> None:
    """A 429 from Brave surfaces as an HTTPStatusError; the aggregator owns degradation."""
    backend = BraveBackend(api_key=_BRAVE_KEY)
    with respx.mock:
        respx.get(BRAVE_SEARCH_URL).mock(return_value=httpx.Response(429))
        with pytest.raises(httpx.HTTPStatusError):
            await backend.search("marie curie")


async def test_brave_backend_request_carries_auth_and_query_params() -> None:
    """The request authenticates with the subscription token and asks for 20 JSON results."""
    backend = BraveBackend(api_key=_BRAVE_KEY)
    with respx.mock:
        route = respx.get(BRAVE_SEARCH_URL).mock(
            return_value=httpx.Response(200, json=_BRAVE_EMPTY_RESPONSE)
        )
        await backend.search("marie curie")

    request = route.calls.last.request
    assert request.headers["X-Subscription-Token"] == _BRAVE_KEY
    assert request.headers["Accept"] == "application/json"
    assert request.url.params["q"] == "marie curie"
    assert int(request.url.params["count"]) == 20

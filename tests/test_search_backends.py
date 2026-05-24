"""Contract tests for individual search backends."""

from typing import Any

import httpx
import pytest
import respx

from odin.search.brave import BRAVE_SEARCH_URL, BraveBackend
from odin.search.wikipedia import WikipediaBackend

_WIKIPEDIA_URL = "https://api.wikimedia.org/core/v1/wikipedia/en/search/page"

# Shape mirrors a real Wikimedia Core REST search response: the first page's
# excerpt carries <span class="searchmatch"> tags and an &amp; entity to prove
# stripping; the second exercises the null-able optional fields.
_WIKIPEDIA_SEARCH_RESPONSE = {
    "pages": [
        {
            "id": 20408,
            "key": "Marie_Curie",
            "title": "Marie Curie",
            "excerpt": (
                'Marie <span class="searchmatch">Curie</span> was a '
                "physicist &amp; chemist who conducted pioneering research."
            ),
            "matched_title": None,
            "description": "Polish-French physicist and chemist (1867 to 1934)",
            "thumbnail": {
                "mimetype": "image/jpeg",
                "url": "//upload.wikimedia.org/wikipedia/commons/thumb/marie.jpg",
                "width": 60,
                "height": 80,
            },
        },
        {
            "id": 24481,
            "key": "Pierre_Curie",
            "title": "Pierre Curie",
            "excerpt": 'Pierre <span class="searchmatch">Curie</span> was a French physicist.',
            "matched_title": "Pierre Curie (physicist)",
            "description": None,
            "thumbnail": None,
        },
    ]
}

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


@respx.mock
async def test_wikipedia_backend_maps_pages_to_search_results() -> None:
    """Each Wikimedia page maps to a SearchResult with a wiki URL built from its key."""
    respx.get(_WIKIPEDIA_URL).mock(
        return_value=httpx.Response(200, json=_WIKIPEDIA_SEARCH_RESPONSE)
    )
    backend = WikipediaBackend()
    out = await backend.search("marie curie")
    assert [r.url for r in out] == [
        "https://en.wikipedia.org/wiki/Marie_Curie",
        "https://en.wikipedia.org/wiki/Pierre_Curie",
    ]
    assert [r.title for r in out] == ["Marie Curie", "Pierre Curie"]


@respx.mock
async def test_wikipedia_backend_strips_html_and_entities_from_excerpt() -> None:
    """The HTML searchmatch markup and entities are reduced to plain text content."""
    respx.get(_WIKIPEDIA_URL).mock(
        return_value=httpx.Response(200, json=_WIKIPEDIA_SEARCH_RESPONSE)
    )
    backend = WikipediaBackend()
    out = await backend.search("marie curie")
    content = out[0].content
    assert "<span" not in content
    assert "searchmatch" not in content
    assert "&amp;" not in content
    assert "physicist & chemist" in content


@respx.mock
async def test_wikipedia_backend_stamps_wikipedia_engine() -> None:
    """Every result is stamped engines==['wikipedia'] for provenance."""
    respx.get(_WIKIPEDIA_URL).mock(
        return_value=httpx.Response(200, json=_WIKIPEDIA_SEARCH_RESPONSE)
    )
    backend = WikipediaBackend()
    out = await backend.search("marie curie")
    assert all(r.engines == ["wikipedia"] for r in out)


@respx.mock
async def test_wikipedia_backend_sends_user_agent_and_params_without_auth() -> None:
    """The request carries a User-Agent and q/limit params, and sends no Authorization header."""
    route = respx.get(_WIKIPEDIA_URL).mock(
        return_value=httpx.Response(200, json=_WIKIPEDIA_SEARCH_RESPONSE)
    )
    backend = WikipediaBackend()
    await backend.search("marie curie")
    request = route.calls.last.request
    assert request.headers["User-Agent"]
    assert "Authorization" not in request.headers
    assert request.url.params["q"] == "marie curie"
    assert request.url.params["limit"] == "10"


@respx.mock
async def test_wikipedia_backend_returns_empty_for_no_pages() -> None:
    """An empty pages list yields no results."""
    respx.get(_WIKIPEDIA_URL).mock(return_value=httpx.Response(200, json={"pages": []}))
    backend = WikipediaBackend()
    assert await backend.search("nobody") == []


@respx.mock
async def test_wikipedia_backend_raises_on_http_error() -> None:
    """A 429 (or any non-2xx) surfaces as an HTTPStatusError for the aggregator to guard."""
    respx.get(_WIKIPEDIA_URL).mock(return_value=httpx.Response(429))
    backend = WikipediaBackend()
    with pytest.raises(httpx.HTTPStatusError):
        await backend.search("marie curie")

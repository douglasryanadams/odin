"""Tests for the main application routes."""

import json
from collections.abc import Iterator, Mapping
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from helpers import api_response, tool_block
from odin.main import app, get_anthropic_client, get_searxng_url

MOCK_BASE_URL = "http://test-searxng:8080"
_MOCK_SEARXNG_RESULTS = {
    "results": [
        {"url": "https://example.com", "title": "Example", "content": "Example content"},
    ]
}


def _mock_url() -> str:
    return MOCK_BASE_URL


@pytest.fixture(autouse=True)
def _override_searxng_url() -> Iterator[None]:  # pyright: ignore[reportUnusedFunction]
    app.dependency_overrides[get_searxng_url] = _mock_url
    yield
    app.dependency_overrides.pop(get_searxng_url, None)


@pytest.fixture
def client() -> TestClient:
    """Return a TestClient bound to the app."""
    return TestClient(app)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


def test_health(client: TestClient) -> None:
    """Verify the health endpoint returns 200 with status ok."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# Index route
# ---------------------------------------------------------------------------


def test_index_renders_wordmark_and_form(client: TestClient) -> None:
    """Index renders the Odin wordmark and search form."""
    response = client.get("/")
    assert response.status_code == 200
    assert ">ODIN<" in response.text
    assert 'id="search-form"' in response.text


def test_static_assets_mounted(client: TestClient) -> None:
    """The /static mount serves the local stylesheet."""
    response = client.get("/static/css/odin.css")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/css")


# ---------------------------------------------------------------------------
# Profile routes
# ---------------------------------------------------------------------------

_MOCK_PROFILE_INPUT: Mapping[str, object] = {
    "name": "foo",
    "category": "other",
    "summary": "A test subject.",
    "highlights": [],
    "lowlights": [],
    "timeline": [],
    "citations": ["https://example.com"],
}


def _pipeline_side_effects() -> list[MagicMock]:
    """Return messages.create responses for a minimal end-to-end pipeline run."""
    return [
        api_response([tool_block("categorize_result", {"category": "other"})]),
        api_response([tool_block("generate_queries_result", {"queries": ["q1"]})]),
        api_response([tool_block("select_urls_result", {"urls": ["https://example.com"]})]),
        api_response([tool_block("create_profile", _MOCK_PROFILE_INPUT)]),
    ]


@pytest.fixture
def mock_anthropic() -> Iterator[MagicMock]:
    """Override get_anthropic_client with a mock whose messages.create is async."""
    mock = MagicMock()
    mock.messages.create = AsyncMock()
    app.dependency_overrides[get_anthropic_client] = lambda: mock
    yield mock
    app.dependency_overrides.pop(get_anthropic_client, None)


def test_profile_page_renders_grid_skeleton(client: TestClient) -> None:
    """Profile page renders the card grid skeleton and references the static JS."""
    response = client.get("/profile?q=foo")
    assert response.status_code == 200
    assert 'id="card-grid"' in response.text
    assert "/static/js/profile.js" in response.text


def _parse_sse_events(body: str) -> list[dict[str, object]]:
    """Parse the body of an SSE response into a list of decoded JSON events."""
    return [json.loads(line[5:]) for line in body.splitlines() if line.startswith("data:")]


@respx.mock
def test_profile_stream_returns_sse(client: TestClient, mock_anthropic: MagicMock) -> None:
    """Profile stream returns text/event-stream with SSE data lines covering all stages."""
    mock_anthropic.messages.create.side_effect = _pipeline_side_effects()
    respx.get(f"{MOCK_BASE_URL}/search").mock(
        return_value=httpx.Response(200, json=_MOCK_SEARXNG_RESULTS)
    )
    respx.get("https://example.com").mock(return_value=httpx.Response(200, text="<p>Content</p>"))

    response = client.get("/profile/stream?q=foo")

    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]
    assert 'data: {"type": "fetching"' in response.text
    mock_anthropic.messages.create.assert_called()

    events = _parse_sse_events(response.text)
    profile_event = next(e for e in events if e["type"] == "profile")
    assert profile_event["citations"] == [
        {"url": "https://example.com", "title": "Example", "snippet": "Example content"},
    ]


@respx.mock
def test_profile_stream_citations_only_include_urls_synthesizer_cited(
    client: TestClient, mock_anthropic: MagicMock
) -> None:
    """Citations come from synthesizer output, not the broader pool of fetched URLs."""
    searxng_results = {
        "results": [
            {"url": "https://a.example", "title": "A", "content": "A snippet"},
            {"url": "https://b.example", "title": "B", "content": "B snippet"},
            {"url": "https://c.example", "title": "C", "content": "C snippet"},
        ]
    }
    profile_input = {
        **_MOCK_PROFILE_INPUT,
        "citations": ["https://b.example", "https://a.example"],
    }
    mock_anthropic.messages.create.side_effect = [
        api_response([tool_block("categorize_result", {"category": "other"})]),
        api_response([tool_block("generate_queries_result", {"queries": ["q1"]})]),
        api_response(
            [
                tool_block(
                    "select_urls_result",
                    {"urls": ["https://a.example", "https://b.example", "https://c.example"]},
                )
            ]
        ),
        api_response([tool_block("create_profile", profile_input)]),
    ]
    respx.get(f"{MOCK_BASE_URL}/search").mock(
        return_value=httpx.Response(200, json=searxng_results)
    )
    respx.get("https://a.example").mock(return_value=httpx.Response(200, text="<p>A</p>"))
    respx.get("https://b.example").mock(return_value=httpx.Response(200, text="<p>B</p>"))
    respx.get("https://c.example").mock(return_value=httpx.Response(200, text="<p>C</p>"))

    response = client.get("/profile/stream?q=foo")

    profile_event = next(e for e in _parse_sse_events(response.text) if e["type"] == "profile")
    assert profile_event["citations"] == [
        {"url": "https://b.example", "title": "B", "snippet": "B snippet"},
        {"url": "https://a.example", "title": "A", "snippet": "A snippet"},
    ]


@respx.mock
def test_profile_stream_omits_citations_for_urls_not_in_search_results(
    client: TestClient, mock_anthropic: MagicMock
) -> None:
    """A URL the synthesizer cites that's missing from search results is silently dropped."""
    profile_input = {
        **_MOCK_PROFILE_INPUT,
        "citations": ["https://example.com", "https://hallucinated.example/"],
    }
    mock_anthropic.messages.create.side_effect = [
        api_response([tool_block("categorize_result", {"category": "other"})]),
        api_response([tool_block("generate_queries_result", {"queries": ["q1"]})]),
        api_response([tool_block("select_urls_result", {"urls": ["https://example.com"]})]),
        api_response([tool_block("create_profile", profile_input)]),
    ]
    respx.get(f"{MOCK_BASE_URL}/search").mock(
        return_value=httpx.Response(200, json=_MOCK_SEARXNG_RESULTS)
    )
    respx.get("https://example.com").mock(return_value=httpx.Response(200, text="<p>C</p>"))

    response = client.get("/profile/stream?q=foo")

    profile_event = next(e for e in _parse_sse_events(response.text) if e["type"] == "profile")
    assert profile_event["citations"] == [
        {"url": "https://example.com", "title": "Example", "snippet": "Example content"},
    ]

"""Tests for the main application module."""

from collections.abc import Iterator, Mapping
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from odin.main import app, get_anthropic_client, get_searxng_url

MOCK_BASE_URL = "http://test-searxng:8080"
MOCK_RESULTS = {
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


def test_health(client: TestClient) -> None:
    """Verify the health endpoint returns 200 with status ok."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_index_loads(client: TestClient) -> None:
    """Index page renders the search form."""
    response = client.get("/")
    assert response.status_code == 200
    assert "<form" in response.text


def test_index_no_results_without_query(client: TestClient) -> None:
    """Index page shows no results block when no query is given."""
    response = client.get("/")
    assert response.status_code == 200
    assert "<pre>" not in response.text


@respx.mock
def test_index_search_shows_results(client: TestClient) -> None:
    """Index page renders search results as raw text when a query is provided."""
    respx.get(f"{MOCK_BASE_URL}/search").mock(return_value=httpx.Response(200, json=MOCK_RESULTS))
    response = client.get("/?q=example")
    assert response.status_code == 200
    assert "https://example.com" in response.text
    assert "<pre>" in response.text


@respx.mock
def test_index_preserves_query_in_input(client: TestClient) -> None:
    """The search input retains the submitted query value."""
    respx.get(f"{MOCK_BASE_URL}/search").mock(
        return_value=httpx.Response(200, json={"results": []})
    )
    response = client.get("/?q=hello")
    assert response.status_code == 200
    assert 'value="hello"' in response.text


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
}


def _tool_block(name: str, input_data: Mapping[str, object]) -> MagicMock:
    block = MagicMock()
    block.type = "tool_use"
    block.id = "tool_abc"
    block.name = name
    block.input = input_data
    return block


def _api_response(content: list[MagicMock], stop_reason: str = "end_turn") -> MagicMock:
    resp = MagicMock()
    resp.content = content
    resp.stop_reason = stop_reason
    return resp


def _pipeline_side_effects() -> list[MagicMock]:
    """Return messages.create responses for a minimal end-to-end pipeline run."""
    return [
        _api_response([_tool_block("categorize_result", {"category": "other"})]),
        _api_response([_tool_block("generate_queries_result", {"queries": ["q1"]})]),
        _api_response([_tool_block("select_urls_result", {"urls": ["https://example.com"]})]),
        _api_response([_tool_block("create_profile", _MOCK_PROFILE_INPUT)]),
    ]


@pytest.fixture
def mock_anthropic() -> Iterator[MagicMock]:
    """Override get_anthropic_client with a mock whose messages.create is async."""
    client = MagicMock()
    client.messages.create = AsyncMock()
    app.dependency_overrides[get_anthropic_client] = lambda: client
    yield client
    app.dependency_overrides.pop(get_anthropic_client, None)


def test_profile_page_loads(client: TestClient) -> None:
    """Profile page renders HTML for a given query."""
    response = client.get("/profile?q=foo")
    assert response.status_code == 200
    assert "<body>" in response.text


@respx.mock
def test_profile_stream_returns_sse(client: TestClient, mock_anthropic: MagicMock) -> None:
    """Profile stream returns text/event-stream with SSE data lines covering all stages."""
    mock_anthropic.messages.create.side_effect = _pipeline_side_effects()
    respx.get(f"{MOCK_BASE_URL}/search").mock(return_value=httpx.Response(200, json=MOCK_RESULTS))

    response = client.get("/profile/stream?q=foo")

    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]
    assert "data:" in response.text
    mock_anthropic.messages.create.assert_called()

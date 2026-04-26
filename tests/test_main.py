"""Tests for the main application routes."""

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


def test_index_loads(client: TestClient) -> None:
    """Index page renders the profile search form."""
    response = client.get("/")
    assert response.status_code == 200
    assert "<form" in response.text


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


def test_profile_page_loads(client: TestClient) -> None:
    """Profile page renders HTML for a given query."""
    response = client.get("/profile?q=foo")
    assert response.status_code == 200
    assert "<body>" in response.text


@respx.mock
def test_profile_stream_returns_sse(client: TestClient, mock_anthropic: MagicMock) -> None:
    """Profile stream returns text/event-stream with SSE data lines covering all stages."""
    mock_anthropic.messages.create.side_effect = _pipeline_side_effects()
    respx.get(f"{MOCK_BASE_URL}/search").mock(
        return_value=httpx.Response(200, json=_MOCK_SEARXNG_RESULTS)
    )

    response = client.get("/profile/stream?q=foo")

    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]
    assert "data:" in response.text
    mock_anthropic.messages.create.assert_called()

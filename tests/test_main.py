"""Tests for the main application module."""

from collections.abc import Iterator

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from main import app, get_searxng_url

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

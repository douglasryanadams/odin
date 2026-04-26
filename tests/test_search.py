"""Unit tests for the /search route."""

from collections.abc import Iterator

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from odin.main import app, get_searxng_url

MOCK_BASE_URL = "http://test-searxng:8080"
MOCK_RESULTS = {
    "results": [
        {"url": "https://python.org", "title": "Python", "content": "Python is great"},
        {"url": "https://docs.python.org", "title": "Python Docs", "content": ""},
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


@respx.mock
def test_search_returns_results(client: TestClient) -> None:
    """Results from SearXNG are parsed and returned."""
    respx.get(f"{MOCK_BASE_URL}/search").mock(return_value=httpx.Response(200, json=MOCK_RESULTS))
    response = client.get("/search?q=python")
    assert response.status_code == 200
    results = response.json()
    assert len(results) == 2
    assert results[0]["url"] == "https://python.org"
    assert results[0]["title"] == "Python"
    assert results[0]["content"] == "Python is great"


@respx.mock
def test_search_empty_results(client: TestClient) -> None:
    """An empty results list from SearXNG is returned as-is."""
    respx.get(f"{MOCK_BASE_URL}/search").mock(
        return_value=httpx.Response(200, json={"results": []})
    )
    response = client.get("/search?q=xyzzy")
    assert response.status_code == 200
    assert response.json() == []


def test_search_searxng_error() -> None:
    """A SearXNG 5xx response surfaces as a 500 to the caller."""
    with respx.mock:
        respx.get(f"{MOCK_BASE_URL}/search").mock(return_value=httpx.Response(500))
        error_client = TestClient(app, raise_server_exceptions=False)
        response = error_client.get("/search?q=python")
    assert response.status_code == 500


def test_search_missing_query(client: TestClient) -> None:
    """Missing query parameter returns 422."""
    response = client.get("/search")
    assert response.status_code == 422

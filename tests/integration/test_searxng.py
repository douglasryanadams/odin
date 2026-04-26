"""Integration tests for the SearXNG integration.

Run with: make test-integration
Requires: docker compose up -d
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from main import app, get_searxng_url

SEARXNG_URL = "http://searxng:8080"


def _real_url() -> str:
    return SEARXNG_URL


@pytest.fixture
def client() -> Iterator[TestClient]:
    """Return a TestClient pointed at the real SearXNG container."""
    app.dependency_overrides[get_searxng_url] = _real_url
    yield TestClient(app)
    app.dependency_overrides.pop(get_searxng_url, None)


@pytest.mark.integration
def test_search_returns_list(client: TestClient) -> None:
    """A real search query returns a list of results."""
    response = client.get("/search?q=python")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


@pytest.mark.integration
def test_search_results_have_expected_shape(client: TestClient) -> None:
    """Each result has the required fields."""
    response = client.get("/search?q=python")
    results = response.json()
    if results:
        assert "url" in results[0]
        assert "title" in results[0]
        assert "content" in results[0]

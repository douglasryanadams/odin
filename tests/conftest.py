"""Pytest configuration: env defaults plus fixtures shared across test modules."""

import os
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

os.environ.setdefault("LOG_LEVEL", "DEBUG")
os.environ.setdefault("SECRET_KEY", "test-only-insecure-secret-key-do-not-use")
os.environ.setdefault("APP_URL", "http://localhost:8000")


import pytest
from fastapi.testclient import TestClient

from odin.app import app, get_search_aggregator, get_valkey_client
from odin.search import SearchAggregator, SearXngBackend

REPO_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = REPO_ROOT / "static"
TEST_SECRET = b"test-only-insecure-secret-key-do-not-use"
MOCK_SEARXNG_BASE_URL = "http://test-searxng:8080"


def _mock_search_aggregator() -> SearchAggregator:
    """Route searches through a single SearXNG backend at the mock URL.

    Tests still mock the SearXNG HTTP endpoint with respx, so this keeps the
    search edge identical to before the aggregator was introduced.
    """
    return SearchAggregator(backends=(SearXngBackend(base_url=MOCK_SEARXNG_BASE_URL),))


@pytest.fixture
def mock_valkey() -> MagicMock:
    """Mock Valkey client covering the methods used by the app under test."""
    m = MagicMock()
    m.get = AsyncMock(return_value=None)
    m.lrange = AsyncMock(return_value=[])
    m.incr = AsyncMock(return_value=1)
    m.expireat = AsyncMock()
    m.lpush = AsyncMock()
    m.ltrim = AsyncMock()
    m.expire = AsyncMock()
    m.set = AsyncMock(return_value=True)
    return m


@pytest.fixture(autouse=True)
def _override_search_aggregator() -> Iterator[None]:  # pyright: ignore[reportUnusedFunction]
    """Pin the search dependency to a SearXNG-only aggregator at the mock URL."""
    app.dependency_overrides[get_search_aggregator] = _mock_search_aggregator
    yield
    app.dependency_overrides.pop(get_search_aggregator, None)


@pytest.fixture(autouse=True)
def _override_valkey_client(mock_valkey: MagicMock) -> Iterator[None]:  # pyright: ignore[reportUnusedFunction]
    """Inject the mock Valkey client wherever the app expects the real one."""
    app.dependency_overrides[get_valkey_client] = lambda: mock_valkey
    yield
    app.dependency_overrides.pop(get_valkey_client, None)


@pytest.fixture(autouse=True)
def _set_app_secret() -> None:  # pyright: ignore[reportUnusedFunction]
    """Set app.state.secret_key without running the full lifespan."""
    app.state.secret_key = TEST_SECRET


@pytest.fixture
def client() -> TestClient:
    """Return a TestClient bound to the app."""
    return TestClient(app)

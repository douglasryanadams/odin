"""Pytest configuration: env defaults plus fixtures shared across test modules."""

import os
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

# Hard-set rather than setdefault so unit-test results don't drift with
# developer .env values that docker-compose forwards into the container.
os.environ["LOG_LEVEL"] = "DEBUG"
os.environ["SECRET_KEY"] = "test-only-insecure-secret-key-do-not-use"  # noqa: S105
os.environ["APP_URL"] = "http://localhost:8000"


import pytest
from fastapi.testclient import TestClient

from odin.app import get_search_aggregator, get_valkey_client
from odin.main import app  # imports routes/* as a side effect of route registration
from odin.search import SearchAggregator, SearchResult

REPO_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = REPO_ROOT / "static"
TEST_SECRET = b"test-only-insecure-secret-key-do-not-use"

_DEFAULT_FAKE_RESULTS: tuple[SearchResult, ...] = (
    SearchResult(
        url="https://example.com",
        title="Example",
        content="Example content",
        engines=["fake"],
    ),
)


@dataclass
class FakeSearchBackend:
    """A SearchBackend test double that returns pre-set results.

    Tests that take the ``fake_search`` fixture mutate ``.results`` to override
    what the pipeline sees from search; tests that don't get the default
    one-result payload (matching the canned citation assertion in
    ``test_profile.py``).
    """

    results: list[SearchResult] = field(default_factory=lambda: list(_DEFAULT_FAKE_RESULTS))
    name: str = "fake"
    timeout_seconds: float = 30.0

    async def search(self, query: str) -> list[SearchResult]:  # noqa: ARG002
        """Return a copy of the pre-set results, ignoring the query string."""
        return list(self.results)


@pytest.fixture
def fake_search() -> FakeSearchBackend:
    """Yield the FakeSearchBackend the autouse aggregator override wraps.

    Take this fixture in a test to customize search results: assign a new list
    to ``.results`` before exercising the pipeline.
    """
    return FakeSearchBackend()


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
def _override_search_aggregator(  # pyright: ignore[reportUnusedFunction]
    fake_search: FakeSearchBackend,
) -> Iterator[None]:
    """Pin the search dependency to an aggregator wrapping the FakeSearchBackend."""
    app.dependency_overrides[get_search_aggregator] = lambda: SearchAggregator(
        backends=(fake_search,)
    )
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

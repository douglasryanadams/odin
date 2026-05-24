"""Integration tests for the profile pipeline against real search backends.

Run with: make test-integration
Requires: docker compose up -d odin-valkey

Uses the production search aggregator (Wikipedia always; Brave when
``BRAVE_API_KEY`` is set). Anthropic is mocked so the test asserts that the
pipeline integrates with the real search edge and emits every stage.
"""

import json
from collections.abc import Iterator, Mapping
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from helpers import api_response, tool_block
from odin import routes  # noqa: F401  # pyright: ignore[reportUnusedImport]
from odin.app import app, get_anthropic_client, get_search_aggregator
from odin.config import settings
from odin.search import build_aggregator

_MOCK_PROFILE_DATA: Mapping[str, object] = {
    "name": "Python",
    "category": "other",
    "summary": "A popular programming language.",
    "highlights": [],
    "lowlights": [],
    "timeline": [],
    "citations": ["https://en.wikipedia.org/wiki/Python_(programming_language)"],
}


def _pipeline_responses(queries: list[str]) -> list[MagicMock]:
    """Build the Anthropic side_effect sequence for a full pipeline run."""
    return [
        api_response([tool_block("categorize_result", {"category": "other"})]),
        api_response([tool_block("generate_queries_result", {"queries": queries})]),
        api_response(
            [
                tool_block(
                    "select_urls_result",
                    {"urls": ["https://en.wikipedia.org/wiki/Python_(programming_language)"]},
                )
            ]
        ),
        api_response([tool_block("create_profile", _MOCK_PROFILE_DATA)]),
    ]


@pytest.fixture
def mock_anthropic() -> Iterator[MagicMock]:
    """Override the Anthropic client with an async mock."""
    mock = MagicMock()
    mock.messages.create = AsyncMock()
    app.dependency_overrides[get_anthropic_client] = lambda: mock
    yield mock
    app.dependency_overrides.pop(get_anthropic_client, None)


@pytest.fixture
def client() -> Iterator[TestClient]:
    """Return a TestClient pointed at the real first-party search aggregator.

    Used as a context manager so FastAPI's lifespan runs and launches the
    Playwright Browser stored on ``app.state.browser``.
    """
    app.dependency_overrides[get_search_aggregator] = lambda: build_aggregator(settings)
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.pop(get_search_aggregator, None)


@pytest.mark.integration
def test_profile_stream_emits_all_stages(client: TestClient, mock_anthropic: MagicMock) -> None:
    """Profile stream integrates with real search and emits every pipeline stage."""
    mock_anthropic.messages.create.side_effect = _pipeline_responses(
        ["python programming language"]
    )

    response = client.get("/profile/stream?q=python")

    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]
    events = [
        json.loads(line[5:]) for line in response.text.splitlines() if line.startswith("data:")
    ]
    stage_types = {e["type"] for e in events}
    assert {"categorized", "queries", "searching", "profile", "done"} <= stage_types


@pytest.mark.integration
def test_profile_stream_searching_stage_has_results(
    client: TestClient, mock_anthropic: MagicMock
) -> None:
    """The searching stage reports results found via the real backends."""
    mock_anthropic.messages.create.side_effect = _pipeline_responses(["python language"])

    response = client.get("/profile/stream?q=python")

    events = [
        json.loads(line[5:]) for line in response.text.splitlines() if line.startswith("data:")
    ]
    searching = next(e for e in events if e["type"] == "searching")
    assert searching["result_count"] > 0


@pytest.mark.integration
def test_profile_stream_includes_citations(client: TestClient, mock_anthropic: MagicMock) -> None:
    """The profile event carries a citations list with url/title/snippet entries."""
    mock_anthropic.messages.create.side_effect = _pipeline_responses(["python language"])

    response = client.get("/profile/stream?q=python")

    events = [
        json.loads(line[5:]) for line in response.text.splitlines() if line.startswith("data:")
    ]
    profile_event = next(e for e in events if e["type"] == "profile")
    assert isinstance(profile_event["citations"], list)
    for citation in profile_event["citations"]:
        assert isinstance(citation["url"], str)
        assert citation["url"]
        assert isinstance(citation["title"], str)
        assert isinstance(citation["snippet"], str)

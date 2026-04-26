"""Tests for the claude module."""

from collections.abc import Mapping
from unittest.mock import AsyncMock, MagicMock

import pytest

from odin import claude
from odin.models import Profile
from odin.searxng import SearchResult


def _tool_block(name: str, input_data: Mapping[str, object]) -> MagicMock:
    block = MagicMock()
    block.type = "tool_use"
    block.id = "tool_abc123"
    block.name = name
    block.input = input_data
    return block


def _api_response(content: list[MagicMock], stop_reason: str = "end_turn") -> MagicMock:
    resp = MagicMock()
    resp.content = content
    resp.stop_reason = stop_reason
    return resp


@pytest.fixture
def mock_client() -> MagicMock:
    """Return a mock AsyncAnthropic client with an async messages.create."""
    client = MagicMock()
    client.messages.create = AsyncMock()
    return client


@pytest.mark.asyncio
async def test_categorize_returns_category(mock_client: MagicMock) -> None:
    """categorize() extracts the category from the tool_use response."""
    mock_client.messages.create.return_value = _api_response(
        [_tool_block("categorize_result", {"category": "person"})]
    )
    result = await claude.categorize(mock_client, "Marie Curie")
    assert result == "person"
    mock_client.messages.create.assert_called_once()


@pytest.mark.asyncio
async def test_generate_queries_returns_list(mock_client: MagicMock) -> None:
    """generate_queries() returns a non-empty list of strings."""
    mock_client.messages.create.return_value = _api_response(
        [_tool_block("generate_queries_result", {"queries": ["q1", "q2", "q3"]})]
    )
    result = await claude.generate_queries(mock_client, "Marie Curie", "person")
    assert len(result) >= 1
    assert all(isinstance(q, str) for q in result)
    mock_client.messages.create.assert_called_once()


@pytest.mark.asyncio
async def test_select_urls_returns_subset(mock_client: MagicMock) -> None:
    """select_urls() returns the URLs chosen by the model."""
    results = [SearchResult(url="https://a.com", title="A", content="content")]
    mock_client.messages.create.return_value = _api_response(
        [_tool_block("select_urls_result", {"urls": ["https://a.com"]})]
    )
    selected = await claude.select_urls(mock_client, "Marie Curie", results)
    assert selected == ["https://a.com"]
    mock_client.messages.create.assert_called_once()


@pytest.mark.asyncio
async def test_synthesize_runs_agentic_loop(mock_client: MagicMock) -> None:
    """synthesize() loops through web_fetch tool calls then returns a Profile."""
    web_fetch_call = _tool_block("web_fetch", {"url": "https://example.com"})
    profile_data = {
        "name": "Marie Curie",
        "category": "person",
        "summary": "A pioneering physicist.",
        "highlights": [{"title": "Nobel Prize", "description": "Won twice."}],
        "lowlights": [],
        "timeline": [{"date": "1903", "event": "First Nobel Prize in Physics"}],
    }

    mock_client.messages.create.side_effect = [
        _api_response([web_fetch_call], stop_reason="tool_use"),
        _api_response([_tool_block("create_profile", profile_data)]),
    ]

    result = await claude.synthesize(mock_client, "Marie Curie", "person", ["https://example.com"])

    assert isinstance(result, Profile)
    assert result.name == "Marie Curie"
    assert result.category == "person"
    assert len(result.highlights) == 1
    mock_client.messages.create.assert_called()
    assert mock_client.messages.create.call_count == 2

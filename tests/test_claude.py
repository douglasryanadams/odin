"""Tests for the claude module."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from helpers import api_response, tool_block
from odin import claude
from odin.models import Profile


@pytest.fixture
def mock_client() -> MagicMock:
    """Return a mock AsyncAnthropic client with an async messages.create."""
    client = MagicMock()
    client.messages.create = AsyncMock()
    return client


@pytest.mark.asyncio
async def test_synthesize_runs_agentic_loop(mock_client: MagicMock) -> None:
    """synthesize() loops through web_fetch tool calls then returns a Profile."""
    profile_data = {
        "name": "Marie Curie",
        "category": "person",
        "summary": "A pioneering physicist.",
        "highlights": [{"title": "Nobel Prize", "description": "Won twice."}],
        "lowlights": [],
        "timeline": [{"date": "1903", "event": "First Nobel Prize in Physics"}],
    }
    mock_client.messages.create.side_effect = [
        api_response(
            [tool_block("web_fetch", {"url": "https://example.com"})], stop_reason="tool_use"
        ),
        api_response([tool_block("create_profile", profile_data)]),
    ]

    result = await claude.synthesize(mock_client, "Marie Curie", "person", ["https://example.com"])

    assert isinstance(result, Profile)
    assert result.name == "Marie Curie"
    assert result.category == "person"
    assert len(result.highlights) == 1
    assert mock_client.messages.create.call_count == 2

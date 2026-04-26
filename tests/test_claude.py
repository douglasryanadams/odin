"""Tests for the claude module."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from helpers import api_response, tool_block
from odin import claude
from odin.models import Profile
from odin.searxng import SearchResult

_PROFILE_DATA = {
    "name": "Marie Curie",
    "category": "person",
    "summary": "A pioneering physicist.",
    "highlights": [{"title": "Nobel Prize", "description": "Won twice."}],
    "lowlights": [],
    "timeline": [{"date": "1903", "event": "First Nobel Prize in Physics"}],
}


@pytest.fixture
def mock_client() -> MagicMock:
    """Return a mock AsyncAnthropic client with an async messages.create."""
    client = MagicMock()
    client.messages.create = AsyncMock()
    return client


@pytest.mark.asyncio
async def test_synthesize_makes_single_call_with_content(mock_client: MagicMock) -> None:
    """synthesize() makes exactly one API call and embeds source content in the user message."""
    mock_client.messages.create.return_value = api_response(
        [tool_block("create_profile", _PROFILE_DATA)]
    )
    content = {
        "https://example.com": "Marie Curie was a physicist.",
        "https://other.com": "She won two Nobel Prizes.",
    }

    result = await claude.synthesize(mock_client, "Marie Curie", "person", content)

    assert isinstance(result, Profile)
    assert result.name == "Marie Curie"
    assert mock_client.messages.create.call_count == 1
    user_message = mock_client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "https://example.com" in user_message
    assert "Marie Curie was a physicist." in user_message
    assert "https://other.com" in user_message


@pytest.mark.asyncio
async def test_select_urls_includes_engine_tags(mock_client: MagicMock) -> None:
    """select_urls includes 'Found by' engine tags for results that have engines."""
    mock_client.messages.create.return_value = api_response(
        [tool_block("select_urls_result", {"urls": ["https://example.com"]})]
    )
    results = [
        SearchResult(
            url="https://example.com",
            title="A",
            content="x",
            engines=["google", "bing"],
        ),
        SearchResult(url="https://other.com", title="B", content="y", engines=[]),
    ]

    await claude.select_urls(mock_client, "test", results)

    user_message = mock_client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "Found by: google, bing" in user_message
    assert user_message.count("Found by") == 1

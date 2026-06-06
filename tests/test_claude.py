"""Tests for the claude module."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from helpers import api_response, tool_block
from odin import claude
from odin.models import Profile
from odin.search import SearchResult

_PROFILE_DATA = {
    "name": "Marie Curie",
    "category": "person",
    "summary": "A pioneering physicist.\n\nWon two Nobel Prizes.",
    "highlights": [
        {
            "title": "Nobel Prize",
            "description": "Won the Nobel Prize twice, in Physics and Chemistry.",
            "detail": (
                "First woman to win a Nobel Prize and the only person to win one in two sciences."
            ),
        }
    ],
    "lowlights": [],
    "timeline": [{"date": "1903", "event": "First Nobel Prize in Physics"}],
    "citations": ["https://example.com"],
}


def test_create_profile_tool_schema_requires_detail_on_each_highlight() -> None:
    """The synthesize tool schema asks Claude for `detail` as well as title + description."""
    items = claude._CREATE_PROFILE_TOOL["input_schema"]["properties"]["highlights"]["items"]  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
    assert set(items["required"]) >= {"title", "description", "detail"}
    assert items["properties"]["detail"]["type"] == "string"
    low_items = claude._CREATE_PROFILE_TOOL["input_schema"]["properties"]["lowlights"]["items"]  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
    assert set(low_items["required"]) >= {"title", "description", "detail"}


def test_assess_tool_schema_caveats_are_brief_detail_objects() -> None:
    """The assess tool schema asks Claude for caveats as {brief, detail} objects."""
    caveat_schema = claude._ASSESS_TOOL["input_schema"]["properties"]["caveats"]  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
    item = caveat_schema["items"]
    assert item["type"] == "object"
    assert set(item["required"]) == {"brief", "detail"}


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
    sources = [
        SearchResult(url="https://example.com", title="Example", content="snippet"),
        SearchResult(url="https://other.com", title="Other", content="snippet"),
    ]

    result = await claude.synthesize(mock_client, "Marie Curie", "person", content, sources)

    assert isinstance(result, Profile)
    assert result.name == "Marie Curie"
    assert mock_client.messages.create.call_count == 1
    user_message = mock_client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "https://example.com" in user_message
    assert "Marie Curie was a physicist." in user_message
    assert "https://other.com" in user_message


@pytest.mark.asyncio
async def test_synthesize_citation_resolves_when_content_key_has_trailing_slash(
    mock_client: MagicMock,
) -> None:
    """Citations resolve when the content key URL has a trailing slash the source URL lacks.

    select_urls is a model call; Claude may return a URL with a trailing slash
    even though the original search result did not have one.  The fetcher keys
    content by the URL it received, so synthesize sees the slash form in the
    section header and Claude cites the slash form.  The lookup must still
    resolve it to the matching SearchResult.
    """
    sources = [
        SearchResult(url="https://example.com/page", title="Example Page", content="A snippet"),
    ]
    # Content keyed by the trailing-slash variant (what select_urls returned)
    content = {"https://example.com/page/": "Marie Curie was a physicist."}
    # Claude cites the URL it sees in the section header — the slash form
    profile_data = {**_PROFILE_DATA, "citations": ["https://example.com/page/"]}
    mock_client.messages.create.return_value = api_response(
        [tool_block("create_profile", profile_data)]
    )

    result = await claude.synthesize(mock_client, "Marie Curie", "person", content, sources)

    assert len(result.citations) == 1
    assert result.citations[0].url == "https://example.com/page"
    assert result.citations[0].title == "Example Page"


@pytest.mark.asyncio
async def test_synthesize_citation_resolves_when_source_has_trailing_slash(
    mock_client: MagicMock,
) -> None:
    """Citations resolve when the source URL has a trailing slash the content key lacks."""
    sources = [
        SearchResult(url="https://example.com/page/", title="Example Page", content="A snippet"),
    ]
    content = {"https://example.com/page": "Marie Curie was a physicist."}
    profile_data = {**_PROFILE_DATA, "citations": ["https://example.com/page"]}
    mock_client.messages.create.return_value = api_response(
        [tool_block("create_profile", profile_data)]
    )

    result = await claude.synthesize(mock_client, "Marie Curie", "person", content, sources)

    assert len(result.citations) == 1
    assert result.citations[0].url == "https://example.com/page/"


@pytest.mark.asyncio
async def test_synthesize_citation_dropped_when_url_has_no_matching_source(
    mock_client: MagicMock,
) -> None:
    """A citation URL that does not match any source after normalization is dropped."""
    sources = [
        SearchResult(url="https://example.com/page", title="Example Page", content="snippet"),
    ]
    content = {"https://example.com/page": "Some text."}
    # Claude hallucinates a URL not in sources and not a trailing-slash variant
    profile_data = {**_PROFILE_DATA, "citations": ["https://totally-different.com/other"]}
    mock_client.messages.create.return_value = api_response(
        [tool_block("create_profile", profile_data)]
    )

    result = await claude.synthesize(mock_client, "Marie Curie", "person", content, sources)

    assert result.citations == []


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

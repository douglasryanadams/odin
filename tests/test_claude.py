"""Tests for the claude module."""

from collections.abc import Iterator, Mapping
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from anthropic import BadRequestError, RateLimitError
from loguru import logger

from helpers import api_response, tool_block
from odin import claude
from odin.config import settings
from odin.models import Profile, ProfileHighlight
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
async def test_call_tool_raises_runtime_error_naming_the_tool_when_block_missing(
    mock_client: MagicMock,
) -> None:
    """_call_tool raises a RuntimeError that names both the caller and the missing tool.

    This is the one path every one of the five Claude-calling functions relies
    on but none of them tests directly — Claude returned a response with no
    matching tool_use block (e.g. it answered in plain text instead).
    """
    mock_client.messages.create.return_value = api_response([])
    spec = claude._ToolCallSpec(  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
        model="claude-haiku-4-5-20251001",
        max_tokens=100,
        system="system prompt",
        tool={"name": "categorize_result", "input_schema": {}},
        error_context="categorize",
    )

    with pytest.raises(RuntimeError, match=r"^categorize: no categorize_result tool block"):
        await claude._call_tool(  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
            mock_client, spec, messages=[{"role": "user", "content": "hello"}]
        )


@pytest.mark.asyncio
async def test_categorize_raises_when_claude_returns_an_unexpected_category(
    mock_client: MagicMock,
) -> None:
    """Categorize raises a clear error if Claude's tool call drifts off its category schema.

    The category crosses straight into an SSE event with no Pydantic model
    downstream to catch a bad value — this is the one place to fail loudly
    before an off-schema string reaches the frontend.
    """
    mock_client.messages.create.return_value = api_response(
        [tool_block("categorize_result", {"category": "robot"})]
    )

    with pytest.raises(RuntimeError, match=r"categorize: unexpected category 'robot' from Claude"):
        await claude.categorize(mock_client, "test query")


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
async def test_find_connections_drops_connections_that_resolve_to_fewer_than_two_sources(
    mock_client: MagicMock,
) -> None:
    """A connection whose citations don't resolve to two distinct sources never ships.

    Citing the same URL twice, or pairing a real URL with one that was never
    fetched, both collapse to fewer than two distinct sources after
    resolution — the gate that keeps the highest fabrication-risk artifact in
    the product from shipping ungrounded. "A connection without its supporting
    citations does not ship."
    """
    sources = [
        SearchResult(url="https://a.com", title="A", content="snippet a"),
        SearchResult(url="https://b.com", title="B", content="snippet b"),
    ]
    content = {"https://a.com": "Text from A.", "https://b.com": "Text from B."}
    connections_data = {
        "connections": [
            {
                "kind": "corroboration",
                "assertion": "Both sources agree on the date.",
                "detail": "Citing the same source twice proves nothing across sources.",
                "citations": ["https://a.com", "https://a.com"],
            },
            {
                "kind": "link",
                "assertion": "A connects to a source that was never fetched.",
                "detail": "One of the two citations does not resolve to a fetched page.",
                "citations": ["https://a.com", "https://unknown.com"],
            },
        ]
    }
    mock_client.messages.create.return_value = api_response(
        [tool_block("find_connections_result", connections_data)]
    )

    result = await claude.find_connections(mock_client, "Test Subject", "other", content, sources)

    assert result == []


@pytest.mark.asyncio
async def test_find_connections_resolves_citations_to_distinct_sources(
    mock_client: MagicMock,
) -> None:
    """A connection grounded in two distinct sources passes through with resolved citations."""
    sources = [
        SearchResult(url="https://a.com", title="A", content="snippet a"),
        SearchResult(url="https://b.com", title="B", content="snippet b"),
    ]
    content = {"https://a.com": "Text from A.", "https://b.com": "Text from B."}
    connections_data = {
        "connections": [
            {
                "kind": "contradiction",
                "assertion": "The sources disagree on the founding year.",
                "detail": "A says 1990; B says 1991.",
                "citations": ["https://a.com", "https://b.com"],
            }
        ]
    }
    mock_client.messages.create.return_value = api_response(
        [tool_block("find_connections_result", connections_data)]
    )

    result = await claude.find_connections(mock_client, "Test Subject", "other", content, sources)

    assert len(result) == 1
    connection = result[0]
    assert connection.kind == "contradiction"
    assert connection.assertion == "The sources disagree on the founding year."
    assert connection.detail == "A says 1990; B says 1991."
    assert {c.url for c in connection.citations} == {"https://a.com", "https://b.com"}
    assert {c.title for c in connection.citations} == {"A", "B"}
    assert {c.snippet for c in connection.citations} == {"snippet a", "snippet b"}


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


def _draft_profile() -> Profile:
    return Profile(
        name="Marie Curie",
        category="person",
        summary="A pioneering physicist.",
        highlights=[
            ProfileHighlight(
                title="Nobel Prize", description="Won twice.", detail="Physics, then Chemistry."
            )
        ],
        lowlights=[],
        timeline=[],
        citations=[],
    )


@pytest.mark.asyncio
async def test_identify_gaps_parses_queries_from_tool_response(mock_client: MagicMock) -> None:
    """identify_gaps returns the follow-up queries Claude proposes via the tool."""
    mock_client.messages.create.return_value = api_response(
        [
            tool_block(
                "identify_gaps_result",
                {"queries": ["Marie Curie early life", "Marie Curie legacy"]},
            )
        ]
    )

    queries = await claude.identify_gaps(mock_client, "Marie Curie", "person", _draft_profile())

    assert queries == ["Marie Curie early life", "Marie Curie legacy"]


@pytest.mark.asyncio
async def test_identify_gaps_feeds_claude_the_formatted_draft_profile(
    mock_client: MagicMock,
) -> None:
    """identify_gaps reuses _format_profile_for_assess to format its input.

    Reusing that formatter — rather than sending raw page content — is what
    keeps this Haiku call cheap and focused on the structured draft, the
    signal that actually helps Claude spot real gaps.
    """
    mock_client.messages.create.return_value = api_response(
        [tool_block("identify_gaps_result", {"queries": []})]
    )
    profile = _draft_profile()

    await claude.identify_gaps(mock_client, "Marie Curie", "person", profile)

    user_message = mock_client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert claude._format_profile_for_assess(profile) in user_message  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]


@pytest.mark.asyncio
async def test_identify_gaps_returns_empty_list_when_draft_looks_complete(
    mock_client: MagicMock,
) -> None:
    """An empty queries list passes through untouched — it's the loop's stop signal."""
    mock_client.messages.create.return_value = api_response(
        [tool_block("identify_gaps_result", {"queries": []})]
    )

    queries = await claude.identify_gaps(mock_client, "Marie Curie", "person", _draft_profile())

    assert queries == []


def _rate_limit_error() -> Exception:
    """Build a real RateLimitError (retryable) backed by an httpx 429 response."""
    response = httpx.Response(429, request=httpx.Request("POST", "https://api.anthropic.com"))
    return RateLimitError("rate limited", response=response, body=None)


def _bad_request_error() -> Exception:
    """Build a real BadRequestError (not retryable) backed by an httpx 400 response."""
    response = httpx.Response(400, request=httpx.Request("POST", "https://api.anthropic.com"))
    return BadRequestError("malformed request", response=response, body=None)


@pytest.fixture(autouse=True)
def mock_sleep() -> Iterator[AsyncMock]:
    """Patch asyncio.sleep in the claude module so retry backoff doesn't slow the suite down.

    Autouse because every test in this module exercises retry paths that sleep
    between attempts; tests that assert on backoff timing request it by name.
    """
    with patch("odin.claude.asyncio.sleep", new_callable=AsyncMock) as sleep:
        yield sleep


_CATEGORIZE_RESPONSE = api_response([tool_block("categorize_result", {"category": "person"})])


@pytest.mark.asyncio
async def test_categorize_retries_transient_error_then_succeeds(
    mock_client: MagicMock, mock_sleep: AsyncMock
) -> None:
    """categorize() retries once on a transient RateLimitError and returns on success."""
    mock_client.messages.create = AsyncMock(side_effect=[_rate_limit_error(), _CATEGORIZE_RESPONSE])

    category = await claude.categorize(mock_client, "Marie Curie")

    assert category == "person"
    assert mock_client.messages.create.call_count == 2
    mock_sleep.assert_awaited_once_with(1.0)


@pytest.mark.asyncio
async def test_categorize_raises_after_exhausting_retry_bound(
    mock_client: MagicMock, mock_sleep: AsyncMock
) -> None:
    """categorize() raises the transient error after exactly max_retries + 1 attempts."""
    mock_client.messages.create = AsyncMock(side_effect=_rate_limit_error())

    with patch.object(settings, "claude_max_retries", 2), pytest.raises(RateLimitError):
        await claude.categorize(mock_client, "Marie Curie")

    assert mock_client.messages.create.call_count == 3
    assert mock_sleep.await_count == 2


@pytest.mark.asyncio
async def test_categorize_does_not_retry_non_retryable_error(
    mock_client: MagicMock, mock_sleep: AsyncMock
) -> None:
    """A permanent error such as BadRequestError propagates on the first attempt."""
    mock_client.messages.create = AsyncMock(side_effect=_bad_request_error())

    with pytest.raises(BadRequestError):
        await claude.categorize(mock_client, "Marie Curie")

    assert mock_client.messages.create.call_count == 1
    mock_sleep.assert_not_awaited()


@pytest.mark.asyncio
async def test_categorize_retry_backoff_doubles_each_attempt(
    mock_client: MagicMock, mock_sleep: AsyncMock
) -> None:
    """Backoff delay doubles with each retry, starting at the base delay."""
    mock_client.messages.create = AsyncMock(
        side_effect=[_rate_limit_error(), _rate_limit_error(), _CATEGORIZE_RESPONSE]
    )

    await claude.categorize(mock_client, "Marie Curie")

    assert [c.args[0] for c in mock_sleep.await_args_list] == [1.0, 2.0]


@pytest.mark.asyncio
async def test_categorize_logs_stage_name_when_retries_exhausted(
    mock_client: MagicMock,
) -> None:
    """Exhausting retries emits exactly one ERROR record naming the failed stage."""
    mock_client.messages.create = AsyncMock(side_effect=_rate_limit_error())
    records: list[dict[str, object]] = []
    sink_id = logger.add(
        lambda msg: records.append(
            {"level": msg.record["level"].name, "message": msg.record["message"]}
        ),
        level="WARNING",
    )
    try:
        with patch.object(settings, "claude_max_retries", 1), pytest.raises(RateLimitError):
            await claude.categorize(mock_client, "Marie Curie")
    finally:
        logger.remove(sink_id)

    errors = [r for r in records if r["level"] == "ERROR"]
    assert len(errors) == 1, f"expected exactly one ERROR, got {records}"
    assert "categorize" in str(errors[0]["message"])


@pytest.mark.asyncio
async def test_generate_queries_retries_transient_error_then_succeeds(
    mock_client: MagicMock,
) -> None:
    """generate_queries is wired through the retry wrapper like categorize."""
    response = api_response([tool_block("generate_queries_result", {"queries": ["q1", "q2"]})])
    mock_client.messages.create = AsyncMock(side_effect=[_rate_limit_error(), response])

    queries = await claude.generate_queries(mock_client, "Marie Curie", "person")

    assert queries == ["q1", "q2"]
    assert mock_client.messages.create.call_count == 2


@pytest.mark.asyncio
async def test_select_urls_retries_transient_error_then_succeeds(
    mock_client: MagicMock,
) -> None:
    """select_urls is wired through the retry wrapper like categorize."""
    response = api_response([tool_block("select_urls_result", {"urls": ["https://example.com"]})])
    mock_client.messages.create = AsyncMock(side_effect=[_rate_limit_error(), response])
    results = [SearchResult(url="https://example.com", title="A", content="x")]

    urls = await claude.select_urls(mock_client, "test", results)

    assert urls == ["https://example.com"]
    assert mock_client.messages.create.call_count == 2


@pytest.mark.asyncio
async def test_identify_gaps_retries_transient_error_then_succeeds(
    mock_client: MagicMock,
) -> None:
    """identify_gaps is wired through the retry wrapper like categorize."""
    response = api_response([tool_block("identify_gaps_result", {"queries": ["follow-up query"]})])
    mock_client.messages.create = AsyncMock(side_effect=[_rate_limit_error(), response])

    queries = await claude.identify_gaps(mock_client, "Marie Curie", "person", _draft_profile())

    assert queries == ["follow-up query"]
    assert mock_client.messages.create.call_count == 2


@pytest.mark.asyncio
async def test_synthesize_retries_transient_error_then_succeeds(
    mock_client: MagicMock,
) -> None:
    """synthesize() is wired through the retry wrapper like categorize()."""
    response = api_response([tool_block("create_profile", _PROFILE_DATA)])
    mock_client.messages.create = AsyncMock(side_effect=[_rate_limit_error(), response])
    sources = [SearchResult(url="https://example.com", title="Example", content="snippet")]
    content = {"https://example.com": "Marie Curie was a physicist."}

    profile = await claude.synthesize(mock_client, "Marie Curie", "person", content, sources)

    assert isinstance(profile, Profile)
    assert mock_client.messages.create.call_count == 2


@pytest.mark.asyncio
async def test_assess_retries_transient_error_then_succeeds(
    mock_client: MagicMock,
) -> None:
    """assess() is wired through the retry wrapper like categorize()."""
    assess_data: Mapping[str, object] = {
        "public_sentiment": 0.0,
        "subject_political_bias": 0.0,
        "source_political_bias": 0.0,
        "law_chaos": 0.0,
        "good_evil": 0.0,
        "caveats": [],
    }
    response = api_response([tool_block("assess_profile", assess_data)])
    mock_client.messages.create = AsyncMock(side_effect=[_rate_limit_error(), response])
    profile = Profile(
        name="Marie Curie",
        category="person",
        summary="A physicist.",
        highlights=[],
        lowlights=[],
        timeline=[],
    )
    content = {"https://example.com": "Marie Curie was a physicist."}

    assessment = await claude.assess(mock_client, "Marie Curie", profile, content)

    assert assessment.public_sentiment == 0.0
    assert mock_client.messages.create.call_count == 2

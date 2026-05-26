"""Tests for the profile routes: /profile (HTML) and /profile/stream (SSE)."""

import json
from collections.abc import Iterator, Mapping
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from conftest import TEST_SECRET, FakeSearchBackend
from fastapi.testclient import TestClient

from helpers import api_response, tool_block
from odin import auth as _auth
from odin.app import app, get_anthropic_client, get_page_fetcher
from odin.search import SearchResult

_MOCK_PROFILE_INPUT: Mapping[str, object] = {
    "name": "foo",
    "category": "other",
    "summary": "A test subject.",
    "highlights": [],
    "lowlights": [],
    "timeline": [],
    "citations": ["https://example.com"],
}

_MOCK_ASSESSMENT_INPUT: Mapping[str, object] = {
    "public_sentiment": 0.0,
    "subject_political_bias": 0.0,
    "source_political_bias": 0.0,
    "law_chaos": 0.0,
    "good_evil": 0.0,
    "caveats": [
        {"brief": "Limited sources.", "detail": "Only one page returned a usable snippet."}
    ],
}


class _FakePageFetcher:
    """Test PageFetcher that returns canned content for any URL."""

    async def fetch_pages(self, urls: list[str]) -> dict[str, str]:
        return {url: f"<p>Mock content for {url}</p>" for url in urls}


def _setup_page_fetcher() -> None:
    app.dependency_overrides[get_page_fetcher] = _FakePageFetcher


def _pipeline_side_effects() -> list[MagicMock]:
    """Return messages.create responses for a minimal end-to-end pipeline run."""
    return [
        api_response([tool_block("categorize_result", {"category": "other"})]),
        api_response([tool_block("generate_queries_result", {"queries": ["q1"]})]),
        api_response([tool_block("select_urls_result", {"urls": ["https://example.com"]})]),
        api_response([tool_block("create_profile", _MOCK_PROFILE_INPUT)]),
        api_response([tool_block("assess_profile", _MOCK_ASSESSMENT_INPUT)]),
    ]


@pytest.fixture
def mock_anthropic() -> Iterator[MagicMock]:
    """Override get_anthropic_client with a mock whose messages.create is async."""
    mock = MagicMock()
    mock.messages.create = AsyncMock()
    app.dependency_overrides[get_anthropic_client] = lambda: mock
    yield mock
    app.dependency_overrides.pop(get_anthropic_client, None)


def _parse_sse_events(body: str) -> list[dict[str, object]]:
    """Parse the body of an SSE response into a list of decoded JSON events."""
    return [json.loads(line[5:]) for line in body.splitlines() if line.startswith("data:")]


def _stateful_kv(mock_valkey: MagicMock) -> dict[str, bytes]:
    """Replace mock_valkey.get/set with a real-ish in-memory backing store."""
    storage: dict[str, bytes] = {}

    async def _get(key: str) -> bytes | None:
        return storage.get(key)

    async def _set(key: str, value: str | bytes, **_kw: object) -> bool:
        storage[key] = value.encode() if isinstance(value, str) else value
        return True

    mock_valkey.get = AsyncMock(side_effect=_get)
    mock_valkey.set = AsyncMock(side_effect=_set)
    return storage


def _make_rate_limit_error() -> Exception:
    from anthropic import RateLimitError  # noqa: PLC0415

    response = httpx.Response(429, request=httpx.Request("POST", "https://api.anthropic.com"))
    return RateLimitError("rate limited", response=response, body=None)


def _make_billing_error() -> Exception:
    from anthropic import BadRequestError  # noqa: PLC0415

    response = httpx.Response(400, request=httpx.Request("POST", "https://api.anthropic.com"))
    return BadRequestError(
        "billing limit reached",
        response=response,
        body={"error": {"type": "billing_error", "message": "spend limit"}},
    )


# ---------------------------------------------------------------------------
# Profile page (HTML)
# ---------------------------------------------------------------------------


def test_profile_page_rejects_overlong_query(client: TestClient) -> None:
    """A query above the cap returns 422 from FastAPI's built-in validation."""
    long_q = "a" * 257
    response = client.get(f"/profile?q={long_q}")
    assert response.status_code == 422


def test_profile_page_accepts_query_at_cap(client: TestClient) -> None:
    """A query at exactly the cap renders normally."""
    boundary_q = "a" * 256
    response = client.get(f"/profile?q={boundary_q}")
    assert response.status_code == 200


def test_profile_stream_rejects_overlong_query(client: TestClient) -> None:
    """The stream endpoint returns 422 for an overlong query."""
    _setup_page_fetcher()
    try:
        long_q = "a" * 257
        response = client.get(f"/profile/stream?q={long_q}")
        assert response.status_code == 422
    finally:
        app.dependency_overrides.pop(get_page_fetcher, None)


def test_profile_page_loads_static_js(client: TestClient) -> None:
    """Profile page references the static JS bundle so streamed events have a renderer."""
    response = client.get("/profile?q=foo")
    assert response.status_code == 200
    assert "/static/js/profile.js" in response.text


def test_profile_page_shows_quota_after_first_search(
    client: TestClient, mock_valkey: MagicMock
) -> None:
    """Profile header shows remaining quota once the user has made at least one search."""
    mock_valkey.get.return_value = b"1"
    response = client.get("/profile?q=foo", cookies={"odin_anon": "test-cookie"})
    assert "free" in response.text


def test_profile_page_hides_quota_on_first_visit(client: TestClient) -> None:
    """Profile header shows no quota on a brand-new visit."""
    response = client.get("/profile?q=foo")
    assert "free" not in response.text


def test_profile_page_sets_anon_cookie_on_first_visit(client: TestClient) -> None:
    """Profile page sets odin_anon cookie when not already present."""
    response = client.get("/profile?q=foo", cookies={})
    assert "odin_anon" in response.cookies


def test_profile_page_signed_in_links_to_dashboard(client: TestClient) -> None:
    """Profile header exposes a Dashboard link for signed-in users."""
    session = _auth.create_session_value("user@example.com", TEST_SECRET)
    response = client.get("/profile?q=foo", cookies={"odin_session": session})
    assert response.status_code == 200
    assert 'href="/dashboard"' in response.text


def test_profile_page_signed_in_has_signout(client: TestClient) -> None:
    """Profile header exposes a POST sign-out form for signed-in users."""
    session = _auth.create_session_value("user@example.com", TEST_SECRET)
    response = client.get("/profile?q=foo", cookies={"odin_session": session})
    assert response.status_code == 200
    assert 'action="/auth/logout"' in response.text


def test_profile_page_anonymous_first_visit_links_to_login(client: TestClient) -> None:
    """Anonymous visitors see a Sign in link on the profile page even before their first search."""
    response = client.get("/profile?q=foo")
    assert response.status_code == 200
    assert 'href="/login"' in response.text


def test_profile_has_meta_description_no_og(client: TestClient) -> None:
    """Profile keeps its dynamic title + description but does not expose OG tags."""
    response = client.get("/profile?q=Ada%20Lovelace")
    assert response.status_code == 200
    body = response.text
    assert '<meta name="description"' in body
    assert "Ada Lovelace" in body
    assert "<title>" in body
    assert "og:title" not in body
    assert "twitter:card" not in body


def test_profile_has_single_h1(client: TestClient) -> None:
    """Profile page has exactly one <h1> (sidebar was demoted to <h2>)."""
    response = client.get("/profile?q=foo")
    assert response.status_code == 200
    assert response.text.count("<h1") == 1


# ---------------------------------------------------------------------------
# Profile stream (SSE)
# ---------------------------------------------------------------------------


def test_profile_stream_emits_service_unavailable_on_rate_limit_error(
    client: TestClient, mock_anthropic: MagicMock
) -> None:
    """When Anthropic rate-limits us, the stream emits service_unavailable and stops."""
    _setup_page_fetcher()
    mock_anthropic.messages.create.side_effect = _make_rate_limit_error()
    response = client.get("/profile/stream?q=foo")
    events = _parse_sse_events(response.text)
    assert any(e["type"] == "service_unavailable" for e in events)


def test_profile_stream_emits_service_unavailable_on_billing_error(
    client: TestClient, mock_anthropic: MagicMock
) -> None:
    """When the workspace spend limit is hit, the stream emits service_unavailable."""
    _setup_page_fetcher()
    mock_anthropic.messages.create.side_effect = _make_billing_error()
    response = client.get("/profile/stream?q=foo")
    events = _parse_sse_events(response.text)
    assert any(e["type"] == "service_unavailable" for e in events)


def test_profile_stream_caches_and_replays_results(
    client: TestClient, mock_anthropic: MagicMock, mock_valkey: MagicMock
) -> None:
    """Second call for the same query replays cached events; pipeline is not re-run."""
    _setup_page_fetcher()
    _stateful_kv(mock_valkey)
    mock_anthropic.messages.create.side_effect = _pipeline_side_effects()

    first = client.get("/profile/stream?q=einstein")
    first_events = _parse_sse_events(first.text)
    first_call_count = mock_anthropic.messages.create.call_count

    second = client.get("/profile/stream?q=einstein")
    second_events = _parse_sse_events(second.text)

    assert mock_anthropic.messages.create.call_count == first_call_count  # no extra calls
    assert {e["type"] for e in second_events} == {e["type"] for e in first_events}


def test_profile_stream_cache_normalizes_query(
    client: TestClient, mock_anthropic: MagicMock, mock_valkey: MagicMock
) -> None:
    """Different whitespace/case for the same logical query hit the same cache entry."""
    _setup_page_fetcher()
    _stateful_kv(mock_valkey)
    mock_anthropic.messages.create.side_effect = _pipeline_side_effects()

    client.get("/profile/stream?q=Albert%20Einstein")
    first_call_count = mock_anthropic.messages.create.call_count

    client.get("/profile/stream?q=%20%20albert%20%20einstein%20%20")

    assert mock_anthropic.messages.create.call_count == first_call_count


def test_profile_stream_cache_hit_does_not_count_against_quota(
    client: TestClient,
    mock_anthropic: MagicMock,
    mock_valkey: MagicMock,
    mock_db_pool: MagicMock,
) -> None:
    """Cache hit serves the result without consuming quota, but still records history.

    A cached response costs us nothing upstream, so the quota counter must not
    advance; the request still belongs in the user's recent-search history. Only
    history writes hit the db pool in this flow, so its execute count tracks them.
    """
    _setup_page_fetcher()
    _stateful_kv(mock_valkey)
    mock_anthropic.messages.create.side_effect = _pipeline_side_effects()

    def _rate_incr_count() -> int:
        return sum(
            1
            for call in mock_valkey.incr.call_args_list
            if call.args and str(call.args[0]).startswith("rate:")
        )

    client.get("/profile/stream?q=einstein", cookies={"odin_anon": "test-cookie"})
    rate_incrs_after_fresh = _rate_incr_count()
    history_writes_after_fresh = mock_db_pool.execute.call_count
    assert rate_incrs_after_fresh > 0
    assert history_writes_after_fresh > 0

    client.get("/profile/stream?q=einstein", cookies={"odin_anon": "test-cookie"})

    assert _rate_incr_count() == rate_incrs_after_fresh
    assert mock_db_pool.execute.call_count > history_writes_after_fresh


def test_profile_stream_does_not_cache_service_unavailable(
    client: TestClient, mock_anthropic: MagicMock, mock_valkey: MagicMock
) -> None:
    """A pipeline that trips a billing error must not poison the cache."""
    _setup_page_fetcher()
    _stateful_kv(mock_valkey)
    mock_anthropic.messages.create.side_effect = _make_billing_error()

    client.get("/profile/stream?q=foo")
    # On the second call, ensure the pipeline runs again rather than serving a cached failure.
    mock_anthropic.messages.create.side_effect = _make_billing_error()
    pre_count = mock_anthropic.messages.create.call_count

    client.get("/profile/stream?q=foo")

    assert mock_anthropic.messages.create.call_count > pre_count


def test_profile_stream_returns_sse(client: TestClient, mock_anthropic: MagicMock) -> None:
    """Profile stream returns text/event-stream with SSE data lines covering all stages."""
    _setup_page_fetcher()
    mock_anthropic.messages.create.side_effect = _pipeline_side_effects()

    response = client.get("/profile/stream?q=foo")

    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]
    assert 'data: {"type": "fetching"' in response.text
    mock_anthropic.messages.create.assert_called()

    events = _parse_sse_events(response.text)
    profile_event = next(e for e in events if e["type"] == "profile")
    assert profile_event["citations"] == [
        {"url": "https://example.com", "title": "Example", "snippet": "Example content"},
    ]


def test_profile_stream_records_query_after_completion(
    client: TestClient,
    mock_anthropic: MagicMock,
    mock_valkey: MagicMock,
    mock_db_pool: MagicMock,
) -> None:
    """Profile stream bumps the ValKey quota counter and writes history to Postgres."""
    _setup_page_fetcher()
    mock_anthropic.messages.create.side_effect = _pipeline_side_effects()
    client.get("/profile/stream?q=foo", cookies={"odin_anon": "test-cookie"})
    mock_valkey.incr.assert_called()
    mock_db_pool.execute.assert_called()


def test_profile_stream_rate_limited_emits_rate_limited_event(
    client: TestClient, mock_valkey: MagicMock
) -> None:
    """When the user is over the daily limit, the first SSE event is rate_limited."""
    _setup_page_fetcher()
    mock_valkey.get.return_value = b"5"
    response = client.get("/profile/stream?q=foo", cookies={"odin_anon": "test-cookie"})
    assert response.status_code == 200
    events = _parse_sse_events(response.text)
    assert events[0]["type"] == "rate_limited"
    assert "redirect" in events[0]


def test_profile_stream_citations_only_include_urls_synthesizer_cited(
    client: TestClient,
    mock_anthropic: MagicMock,
    fake_search: FakeSearchBackend,
) -> None:
    """Citations come from synthesizer output, not the broader pool of fetched URLs."""
    _setup_page_fetcher()
    fake_search.results = [
        SearchResult(url="https://a.example", title="A", content="A snippet", engines=["fake"]),
        SearchResult(url="https://b.example", title="B", content="B snippet", engines=["fake"]),
        SearchResult(url="https://c.example", title="C", content="C snippet", engines=["fake"]),
    ]
    profile_input = {
        **_MOCK_PROFILE_INPUT,
        "citations": ["https://b.example", "https://a.example"],
    }
    mock_anthropic.messages.create.side_effect = [
        api_response([tool_block("categorize_result", {"category": "other"})]),
        api_response([tool_block("generate_queries_result", {"queries": ["q1"]})]),
        api_response(
            [
                tool_block(
                    "select_urls_result",
                    {"urls": ["https://a.example", "https://b.example", "https://c.example"]},
                )
            ]
        ),
        api_response([tool_block("create_profile", profile_input)]),
        api_response([tool_block("assess_profile", _MOCK_ASSESSMENT_INPUT)]),
    ]

    response = client.get("/profile/stream?q=foo")

    profile_event = next(e for e in _parse_sse_events(response.text) if e["type"] == "profile")
    assert profile_event["citations"] == [
        {"url": "https://b.example", "title": "B", "snippet": "B snippet"},
        {"url": "https://a.example", "title": "A", "snippet": "A snippet"},
    ]


def test_profile_stream_omits_citations_for_urls_not_in_search_results(
    client: TestClient, mock_anthropic: MagicMock
) -> None:
    """A URL the synthesizer cites that's missing from search results is silently dropped."""
    _setup_page_fetcher()
    profile_input = {
        **_MOCK_PROFILE_INPUT,
        "citations": ["https://example.com", "https://hallucinated.example/"],
    }
    mock_anthropic.messages.create.side_effect = [
        api_response([tool_block("categorize_result", {"category": "other"})]),
        api_response([tool_block("generate_queries_result", {"queries": ["q1"]})]),
        api_response([tool_block("select_urls_result", {"urls": ["https://example.com"]})]),
        api_response([tool_block("create_profile", profile_input)]),
        api_response([tool_block("assess_profile", _MOCK_ASSESSMENT_INPUT)]),
    ]

    response = client.get("/profile/stream?q=foo")

    profile_event = next(e for e in _parse_sse_events(response.text) if e["type"] == "profile")
    assert profile_event["citations"] == [
        {"url": "https://example.com", "title": "Example", "snippet": "Example content"},
    ]


# ---------------------------------------------------------------------------
# Assessment SSE event
# ---------------------------------------------------------------------------


def test_profile_stream_emits_assessment_after_profile(
    client: TestClient, mock_anthropic: MagicMock
) -> None:
    """An 'assessment' SSE event follows the 'profile' event with the tool payload."""
    _setup_page_fetcher()
    mock_anthropic.messages.create.side_effect = _pipeline_side_effects()

    response = client.get("/profile/stream?q=foo")
    events = _parse_sse_events(response.text)
    types = [e["type"] for e in events]

    assert types.index("assessment") > types.index("profile")
    assess_event = next(e for e in events if e["type"] == "assessment")
    assert "confidence" not in assess_event
    assert assess_event["caveats"] == [
        {"brief": "Limited sources.", "detail": "Only one page returned a usable snippet."}
    ]


def test_profile_stream_assessment_preserves_boundary_values(
    client: TestClient, mock_anthropic: MagicMock
) -> None:
    """Extreme values (-1.0/1.0) and an empty caveats list survive through to the SSE event."""
    _setup_page_fetcher()
    boundary: Mapping[str, object] = {
        "public_sentiment": -1.0,
        "subject_political_bias": 1.0,
        "source_political_bias": -1.0,
        "law_chaos": 1.0,
        "good_evil": -1.0,
        "caveats": [],
    }
    side_effects = _pipeline_side_effects()
    side_effects[-1] = api_response([tool_block("assess_profile", boundary)])
    mock_anthropic.messages.create.side_effect = side_effects

    response = client.get("/profile/stream?q=foo")
    assess_event = next(e for e in _parse_sse_events(response.text) if e["type"] == "assessment")
    assert assess_event == {"type": "assessment", **boundary}


def test_profile_stream_emits_profile_when_assess_fails(
    client: TestClient, mock_anthropic: MagicMock
) -> None:
    """If assess() raises, the profile event still arrives but no assessment event follows."""
    _setup_page_fetcher()
    side_effects = _pipeline_side_effects()
    side_effects[-1] = api_response([])  # no assess_profile tool block — triggers RuntimeError
    mock_anthropic.messages.create.side_effect = side_effects

    response = client.get("/profile/stream?q=foo")
    types = [e["type"] for e in _parse_sse_events(response.text)]

    assert "profile" in types
    assert "assessment" not in types

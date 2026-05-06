"""Tests for the main application routes."""

import json
from collections.abc import Iterator, Mapping
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from helpers import api_response, tool_block
from odin import auth as _auth
from odin.main import (
    app,
    get_anthropic_client,
    get_page_fetcher,
    get_searxng_url,
    get_valkey_client,
)

MOCK_BASE_URL = "http://test-searxng:8080"
_MOCK_SEARXNG_RESULTS = {
    "results": [
        {"url": "https://example.com", "title": "Example", "content": "Example content"},
    ]
}
_TEST_SECRET = b"test-only-insecure-secret-key-do-not-use"


def _mock_url() -> str:
    return MOCK_BASE_URL


@pytest.fixture
def mock_valkey() -> MagicMock:
    m = MagicMock()
    m.get = AsyncMock(return_value=None)
    m.lrange = AsyncMock(return_value=[])
    m.incr = AsyncMock(return_value=1)
    m.expireat = AsyncMock()
    m.lpush = AsyncMock()
    m.ltrim = AsyncMock()
    m.expire = AsyncMock()
    return m


@pytest.fixture(autouse=True)
def _override_searxng_url() -> Iterator[None]:  # pyright: ignore[reportUnusedFunction]
    app.dependency_overrides[get_searxng_url] = _mock_url
    yield
    app.dependency_overrides.pop(get_searxng_url, None)


@pytest.fixture(autouse=True)
def _override_valkey_client(mock_valkey: MagicMock) -> Iterator[None]:  # pyright: ignore[reportUnusedFunction]
    app.dependency_overrides[get_valkey_client] = lambda: mock_valkey
    yield
    app.dependency_overrides.pop(get_valkey_client, None)


@pytest.fixture(autouse=True)
def _set_app_secret() -> None:  # pyright: ignore[reportUnusedFunction]
    """Set app.state.secret_key without running the full lifespan."""
    app.state.secret_key = _TEST_SECRET


class _FakePageFetcher:
    """Test PageFetcher that returns canned content for any URL."""

    async def fetch_pages(self, urls: list[str]) -> dict[str, str]:
        return {url: f"<p>Mock content for {url}</p>" for url in urls}


def _setup_page_fetcher() -> None:
    app.dependency_overrides[get_page_fetcher] = _FakePageFetcher


@pytest.fixture
def client() -> TestClient:
    """Return a TestClient bound to the app."""
    return TestClient(app)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


def test_health(client: TestClient) -> None:
    """Verify the health endpoint returns 200 with status ok."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# Index route
# ---------------------------------------------------------------------------


def test_index_renders_wordmark_and_form(client: TestClient) -> None:
    """Index renders the Odin wordmark and search form."""
    response = client.get("/")
    assert response.status_code == 200
    assert ">ODIN<" in response.text
    assert 'id="search-form"' in response.text


def test_index_sets_anon_cookie_on_first_visit(client: TestClient) -> None:
    """Index sets odin_anon cookie when not already present."""
    response = client.get("/", cookies={})
    assert "odin_anon" in response.cookies


def test_index_does_not_overwrite_existing_anon_cookie(client: TestClient) -> None:
    """Index leaves an existing odin_anon cookie unchanged."""
    response = client.get("/", cookies={"odin_anon": "existing-id"})
    assert "odin_anon" not in response.cookies


def test_index_shows_quota_when_count_is_nonzero(
    client: TestClient, mock_valkey: MagicMock
) -> None:
    """Index renders remaining quota text when the user has made at least one search."""
    mock_valkey.get.return_value = b"1"
    response = client.get("/", cookies={"odin_anon": "existing-id"})
    assert "remaining" in response.text


def test_index_hides_quota_on_first_visit(client: TestClient) -> None:
    """Index shows no quota message when the count is zero (first-time visitor)."""
    response = client.get("/")
    assert "remaining" not in response.text


def test_index_redirects_to_login_when_anon_rate_limited(
    client: TestClient, mock_valkey: MagicMock
) -> None:
    """Anonymous user who has hit their daily limit is redirected to the login page."""
    mock_valkey.get.return_value = b"5"
    response = client.get("/", cookies={"odin_anon": "test-cookie"}, follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/login?reason=limit"


def test_static_assets_mounted(client: TestClient) -> None:
    """The /static mount serves the local stylesheet."""
    response = client.get("/static/css/odin.css")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/css")


# ---------------------------------------------------------------------------
# Profile routes
# ---------------------------------------------------------------------------

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
    "confidence": 0.5,
    "public_sentiment": 0.0,
    "subject_political_bias": 0.0,
    "source_political_bias": 0.0,
    "law_chaos": 0.0,
    "good_evil": 0.0,
    "caveats": ["Limited sources."],
}


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


def test_profile_page_renders_grid_skeleton(client: TestClient) -> None:
    """Profile page renders the card grid skeleton and references the static JS."""
    response = client.get("/profile?q=foo")
    assert response.status_code == 200
    assert 'id="card-grid"' in response.text
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


def _parse_sse_events(body: str) -> list[dict[str, object]]:
    """Parse the body of an SSE response into a list of decoded JSON events."""
    return [json.loads(line[5:]) for line in body.splitlines() if line.startswith("data:")]


@respx.mock
def test_profile_stream_returns_sse(client: TestClient, mock_anthropic: MagicMock) -> None:
    """Profile stream returns text/event-stream with SSE data lines covering all stages."""
    _setup_page_fetcher()
    mock_anthropic.messages.create.side_effect = _pipeline_side_effects()
    respx.get(f"{MOCK_BASE_URL}/search").mock(
        return_value=httpx.Response(200, json=_MOCK_SEARXNG_RESULTS)
    )

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


@respx.mock
def test_profile_stream_records_query_after_completion(
    client: TestClient,
    mock_anthropic: MagicMock,
    mock_valkey: MagicMock,
) -> None:
    """Profile stream calls record_query and push_history after the pipeline finishes."""
    _setup_page_fetcher()
    mock_anthropic.messages.create.side_effect = _pipeline_side_effects()
    respx.get(f"{MOCK_BASE_URL}/search").mock(
        return_value=httpx.Response(200, json=_MOCK_SEARXNG_RESULTS)
    )
    client.get("/profile/stream?q=foo", cookies={"odin_anon": "test-cookie"})
    mock_valkey.incr.assert_called()
    mock_valkey.lpush.assert_called()


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


@respx.mock
def test_profile_stream_citations_only_include_urls_synthesizer_cited(
    client: TestClient, mock_anthropic: MagicMock
) -> None:
    """Citations come from synthesizer output, not the broader pool of fetched URLs."""
    _setup_page_fetcher()
    searxng_results = {
        "results": [
            {"url": "https://a.example", "title": "A", "content": "A snippet"},
            {"url": "https://b.example", "title": "B", "content": "B snippet"},
            {"url": "https://c.example", "title": "C", "content": "C snippet"},
        ]
    }
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
    respx.get(f"{MOCK_BASE_URL}/search").mock(
        return_value=httpx.Response(200, json=searxng_results)
    )

    response = client.get("/profile/stream?q=foo")

    profile_event = next(e for e in _parse_sse_events(response.text) if e["type"] == "profile")
    assert profile_event["citations"] == [
        {"url": "https://b.example", "title": "B", "snippet": "B snippet"},
        {"url": "https://a.example", "title": "A", "snippet": "A snippet"},
    ]


@respx.mock
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
    respx.get(f"{MOCK_BASE_URL}/search").mock(
        return_value=httpx.Response(200, json=_MOCK_SEARXNG_RESULTS)
    )

    response = client.get("/profile/stream?q=foo")

    profile_event = next(e for e in _parse_sse_events(response.text) if e["type"] == "profile")
    assert profile_event["citations"] == [
        {"url": "https://example.com", "title": "Example", "snippet": "Example content"},
    ]


# ---------------------------------------------------------------------------
# Assessment SSE event
# ---------------------------------------------------------------------------


@respx.mock
def test_profile_stream_emits_assessment_after_profile(
    client: TestClient, mock_anthropic: MagicMock
) -> None:
    """An 'assessment' SSE event follows the 'profile' event with the tool payload."""
    _setup_page_fetcher()
    mock_anthropic.messages.create.side_effect = _pipeline_side_effects()
    respx.get(f"{MOCK_BASE_URL}/search").mock(
        return_value=httpx.Response(200, json=_MOCK_SEARXNG_RESULTS)
    )

    response = client.get("/profile/stream?q=foo")
    events = _parse_sse_events(response.text)
    types = [e["type"] for e in events]

    assert types.index("assessment") > types.index("profile")
    assess_event = next(e for e in events if e["type"] == "assessment")
    assert assess_event["confidence"] == 0.5
    assert assess_event["caveats"] == ["Limited sources."]


@respx.mock
def test_profile_stream_assessment_preserves_boundary_values(
    client: TestClient, mock_anthropic: MagicMock
) -> None:
    """Extreme values (-1.0/1.0) and an empty caveats list survive through to the SSE event."""
    _setup_page_fetcher()
    boundary: Mapping[str, object] = {
        "confidence": 1.0,
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
    respx.get(f"{MOCK_BASE_URL}/search").mock(
        return_value=httpx.Response(200, json=_MOCK_SEARXNG_RESULTS)
    )

    response = client.get("/profile/stream?q=foo")
    assess_event = next(e for e in _parse_sse_events(response.text) if e["type"] == "assessment")
    assert assess_event == {"type": "assessment", **boundary}


@respx.mock
def test_profile_stream_emits_profile_when_assess_fails(
    client: TestClient, mock_anthropic: MagicMock
) -> None:
    """If assess() raises, the profile event still arrives but no assessment event follows."""
    _setup_page_fetcher()
    side_effects = _pipeline_side_effects()
    side_effects[-1] = api_response([])  # no assess_profile tool block — triggers RuntimeError
    mock_anthropic.messages.create.side_effect = side_effects
    respx.get(f"{MOCK_BASE_URL}/search").mock(
        return_value=httpx.Response(200, json=_MOCK_SEARXNG_RESULTS)
    )

    response = client.get("/profile/stream?q=foo")
    types = [e["type"] for e in _parse_sse_events(response.text)]

    assert "profile" in types
    assert "assessment" not in types


# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------


def test_login_page_renders(client: TestClient) -> None:
    """GET /login renders the sign-in form."""
    response = client.get("/login")
    assert response.status_code == 200
    assert "Sign in" in response.text
    assert 'action="/auth/send-link"' in response.text


def test_login_page_shows_limit_message_when_reason_is_limit(client: TestClient) -> None:
    """GET /login?reason=limit shows the rate-limit notice."""
    response = client.get("/login?reason=limit")
    assert "free searches for today" in response.text


@patch("odin.main.send_magic_link")
def test_send_link_renders_confirmation(mock_send: MagicMock, client: TestClient) -> None:
    """POST /auth/send-link renders a confirmation and calls send_magic_link."""
    mock_send.return_value = None
    response = client.post("/auth/send-link", data={"email": "user@example.com"})
    assert response.status_code == 200
    assert "user@example.com" in response.text
    mock_send.assert_called_once()


@patch("odin.main.send_magic_link")
def test_send_link_normalizes_email(mock_send: MagicMock, client: TestClient) -> None:
    """POST /auth/send-link lowercases and strips the submitted email."""
    mock_send.return_value = None
    client.post("/auth/send-link", data={"email": "  USER@EXAMPLE.COM  "})
    called_email = mock_send.call_args[0][0]
    assert called_email == "user@example.com"


def test_auth_verify_sets_session_cookie_and_redirects(client: TestClient) -> None:
    """GET /auth/verify with a valid token sets odin_session and redirects to /."""
    token = _auth.generate_magic_token("user@example.com", _TEST_SECRET)
    response = client.get(f"/auth/verify?token={token}", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert "odin_session" in response.cookies


def test_auth_verify_invalid_token_renders_error(client: TestClient) -> None:
    """GET /auth/verify with a bad token renders an error on the login page."""
    response = client.get("/auth/verify?token=garbage.token")
    assert response.status_code == 200
    assert "Invalid or expired" in response.text


def test_auth_logout_clears_session_and_redirects(client: TestClient) -> None:
    """GET /auth/logout deletes the session cookie and redirects to /."""
    response = client.get("/auth/logout", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/"


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


def test_dashboard_redirects_unauthenticated_users(client: TestClient) -> None:
    """GET /dashboard redirects to /login when no valid session exists."""
    response = client.get("/dashboard", follow_redirects=False)
    assert response.status_code == 303
    assert "/login" in response.headers["location"]


def test_dashboard_renders_for_authenticated_user(client: TestClient) -> None:
    """GET /dashboard renders quota and history for a logged-in user."""
    session = _auth.create_session_value("user@example.com", _TEST_SECRET)
    response = client.get("/dashboard", cookies={"odin_session": session})
    assert response.status_code == 200
    assert "user@example.com" in response.text
    assert "searches used today" in response.text

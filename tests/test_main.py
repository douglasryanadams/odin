"""Tests for the main application routes."""

import json
from collections.abc import AsyncIterator, Iterator, Mapping
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
    m.set = AsyncMock(return_value=True)
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


async def _async_iter(items: list[bytes]) -> "AsyncIterator[bytes]":
    for item in items:
        yield item


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


def test_index_renders_beta_badge(client: TestClient) -> None:
    """Landing page includes a beta badge so users know the product is in beta."""
    response = client.get("/")
    assert response.status_code == 200
    assert "beta-badge" in response.text
    assert ">Beta<" in response.text


def test_index_sets_anon_cookie_on_first_visit(client: TestClient) -> None:
    """Index sets odin_anon cookie when not already present."""
    response = client.get("/", cookies={})
    assert "odin_anon" in response.cookies


def test_index_does_not_overwrite_existing_anon_cookie(client: TestClient) -> None:
    """Index leaves an existing odin_anon cookie unchanged."""
    response = client.get("/", cookies={"odin_anon": "existing-id"})
    assert "odin_anon" not in response.cookies


def test_anon_cookie_lacks_secure_flag_in_dev(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When cookie_secure is False (local dev), Set-Cookie omits Secure."""
    from odin import main as _main  # noqa: PLC0415

    monkeypatch.setattr(_main.settings, "cookie_secure", False)
    response = client.get("/", cookies={})
    set_cookie = response.headers.get("set-cookie", "")
    assert "odin_anon=" in set_cookie
    assert "Secure" not in set_cookie


def test_anon_cookie_has_secure_flag_when_enabled(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When cookie_secure is True, Set-Cookie for odin_anon includes Secure."""
    from odin import main as _main  # noqa: PLC0415

    monkeypatch.setattr(_main.settings, "cookie_secure", True)
    response = client.get("/", cookies={})
    set_cookie = response.headers.get("set-cookie", "")
    assert "odin_anon=" in set_cookie
    assert "Secure" in set_cookie


def test_session_cookie_has_secure_flag_when_enabled(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """/auth/verify sets odin_session with Secure when cookie_secure is True."""
    from odin import main as _main  # noqa: PLC0415

    monkeypatch.setattr(_main.settings, "cookie_secure", True)
    token = _auth.generate_magic_token("user@example.com", _TEST_SECRET)
    response = client.get(f"/auth/verify?token={token}", follow_redirects=False)
    set_cookie = response.headers.get("set-cookie", "")
    assert "odin_session=" in set_cookie
    assert "Secure" in set_cookie


def test_auth_verify_rejects_reused_token(client: TestClient, mock_valkey: MagicMock) -> None:
    """A magic-link token can only be redeemed once; replay falls through to login error."""
    # First call: jti claim succeeds (Valkey SET NX returns truthy).
    # Second call: jti already claimed (returns None / falsy).
    mock_valkey.set = AsyncMock(side_effect=[True, None])
    token = _auth.generate_magic_token("user@example.com", _TEST_SECRET)

    first = client.get(f"/auth/verify?token={token}", follow_redirects=False)
    assert "odin_session=" in first.headers.get("set-cookie", "")

    second = client.get(f"/auth/verify?token={token}")
    assert "odin_session=" not in second.headers.get("set-cookie", "")
    assert "Invalid or expired link" in second.text


def test_index_response_has_security_headers(client: TestClient) -> None:
    """All responses carry baseline security headers."""
    response = client.get("/")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert "default-src 'self'" in response.headers["Content-Security-Policy"]


def test_health_response_also_has_security_headers(client: TestClient) -> None:
    """JSON endpoints get the same headers as HTML ones."""
    response = client.get("/health")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert "Content-Security-Policy" in response.headers


def test_hsts_absent_when_cookie_secure_false(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """HSTS is omitted in dev (plain HTTP) so browsers don't pin localhost to HTTPS."""
    from odin import main as _main  # noqa: PLC0415

    monkeypatch.setattr(_main.settings, "cookie_secure", False)
    response = client.get("/")
    assert "Strict-Transport-Security" not in response.headers


def test_hsts_present_when_cookie_secure_true(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """HSTS is set in production where cookie_secure is True."""
    from odin import main as _main  # noqa: PLC0415

    monkeypatch.setattr(_main.settings, "cookie_secure", True)
    response = client.get("/")
    hsts = response.headers["Strict-Transport-Security"]
    assert "max-age=" in hsts
    assert "includeSubDomains" in hsts


def test_csp_allows_required_external_assets(client: TestClient) -> None:
    """CSP must not block the actual fonts and Font Awesome asset hosts in use."""
    response = client.get("/")
    csp = response.headers["Content-Security-Policy"]
    assert "https://fonts.googleapis.com" in csp
    assert "https://fonts.gstatic.com" in csp
    assert "https://cdnjs.cloudflare.com" in csp


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


def test_index_signed_in_links_to_dashboard_without_searches(client: TestClient) -> None:
    """Signed-in users can reach /dashboard from the home page even before their first search."""
    session = _auth.create_session_value("user@example.com", _TEST_SECRET)
    response = client.get("/", cookies={"odin_session": session})
    assert response.status_code == 200
    assert 'href="/dashboard"' in response.text


def test_index_anonymous_first_visit_links_to_login(client: TestClient) -> None:
    """Anonymous visitors see a Sign in link on the home page even before their first search."""
    response = client.get("/")
    assert response.status_code == 200
    assert 'href="/login"' in response.text


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
    "caveats": [
        {"brief": "Limited sources.", "detail": "Only one page returned a usable snippet."}
    ],
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
    session = _auth.create_session_value("user@example.com", _TEST_SECRET)
    response = client.get("/profile?q=foo", cookies={"odin_session": session})
    assert response.status_code == 200
    assert 'href="/dashboard"' in response.text


def test_profile_page_signed_in_has_signout(client: TestClient) -> None:
    """Profile header exposes a POST sign-out form for signed-in users."""
    session = _auth.create_session_value("user@example.com", _TEST_SECRET)
    response = client.get("/profile?q=foo", cookies={"odin_session": session})
    assert response.status_code == 200
    assert 'action="/auth/logout"' in response.text


def test_profile_page_anonymous_first_visit_links_to_login(client: TestClient) -> None:
    """Anonymous visitors see a Sign in link on the profile page even before their first search."""
    response = client.get("/profile?q=foo")
    assert response.status_code == 200
    assert 'href="/login"' in response.text


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


@respx.mock
def test_profile_stream_caches_and_replays_results(
    client: TestClient, mock_anthropic: MagicMock, mock_valkey: MagicMock
) -> None:
    """Second call for the same query replays cached events; pipeline is not re-run."""
    _setup_page_fetcher()
    _stateful_kv(mock_valkey)
    mock_anthropic.messages.create.side_effect = _pipeline_side_effects()
    respx.get(f"{MOCK_BASE_URL}/search").mock(
        return_value=httpx.Response(200, json=_MOCK_SEARXNG_RESULTS)
    )

    first = client.get("/profile/stream?q=einstein")
    first_events = _parse_sse_events(first.text)
    first_call_count = mock_anthropic.messages.create.call_count

    second = client.get("/profile/stream?q=einstein")
    second_events = _parse_sse_events(second.text)

    assert mock_anthropic.messages.create.call_count == first_call_count  # no extra calls
    assert {e["type"] for e in second_events} == {e["type"] for e in first_events}


@respx.mock
def test_profile_stream_cache_normalizes_query(
    client: TestClient, mock_anthropic: MagicMock, mock_valkey: MagicMock
) -> None:
    """Different whitespace/case for the same logical query hit the same cache entry."""
    _setup_page_fetcher()
    _stateful_kv(mock_valkey)
    mock_anthropic.messages.create.side_effect = _pipeline_side_effects()
    respx.get(f"{MOCK_BASE_URL}/search").mock(
        return_value=httpx.Response(200, json=_MOCK_SEARXNG_RESULTS)
    )

    client.get("/profile/stream?q=Albert%20Einstein")
    first_call_count = mock_anthropic.messages.create.call_count

    client.get("/profile/stream?q=%20%20albert%20%20einstein%20%20")

    assert mock_anthropic.messages.create.call_count == first_call_count


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
    assert assess_event["caveats"] == [
        {"brief": "Limited sources.", "detail": "Only one page returned a usable snippet."}
    ]


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


_CSRF = "test-csrf-token"


def _seed_csrf(client: TestClient) -> dict[str, str]:
    """Set a CSRF cookie on the client and return matching form-data."""
    client.cookies.set("csrf_token", _CSRF)
    return {"csrf_token": _CSRF}


@patch("odin.main.send_magic_link")
def test_send_link_renders_confirmation(mock_send: MagicMock, client: TestClient) -> None:
    """POST /auth/send-link renders a confirmation and calls send_magic_link."""
    mock_send.return_value = None
    response = client.post(
        "/auth/send-link",
        data={"email": "user@example.com", **_seed_csrf(client)},
    )
    assert response.status_code == 200
    assert "user@example.com" in response.text
    mock_send.assert_called_once()


@patch("odin.main.send_magic_link")
def test_send_link_normalizes_email(mock_send: MagicMock, client: TestClient) -> None:
    """POST /auth/send-link lowercases and strips the submitted email."""
    mock_send.return_value = None
    client.post(
        "/auth/send-link",
        data={"email": "  USER@EXAMPLE.COM  ", **_seed_csrf(client)},
    )
    called_email = mock_send.call_args[0][0]
    assert called_email == "user@example.com"


def _stateful_incr(mock_valkey: MagicMock) -> dict[str, int]:
    """Wire mock_valkey.incr to maintain real per-key counts; return the dict for inspection."""
    counts: dict[str, int] = {}

    async def _incr(key: str) -> int:
        counts[key] = counts.get(key, 0) + 1
        return counts[key]

    mock_valkey.incr = AsyncMock(side_effect=_incr)
    return counts


@patch("odin.main.send_magic_link")
def test_send_link_rejects_second_email_within_hour_silently(
    mock_send: MagicMock, client: TestClient, mock_valkey: MagicMock
) -> None:
    """Second magic-link request for the same email is silently dropped."""
    _stateful_incr(mock_valkey)
    mock_send.return_value = None
    csrf = _seed_csrf(client)

    first = client.post("/auth/send-link", data={"email": "user@example.com", **csrf})
    second = client.post("/auth/send-link", data={"email": "user@example.com", **csrf})

    assert first.status_code == 200
    assert second.status_code == 200
    assert "user@example.com" in second.text
    assert mock_send.call_count == 1


@patch("odin.main.send_magic_link")
def test_send_link_rejects_sixth_ip_within_hour(
    mock_send: MagicMock, client: TestClient, mock_valkey: MagicMock
) -> None:
    """Six different emails from the same IP within an hour: only five are sent."""
    _stateful_incr(mock_valkey)
    mock_send.return_value = None
    csrf = _seed_csrf(client)

    for i in range(6):
        client.post("/auth/send-link", data={"email": f"u{i}@example.com", **csrf})

    assert mock_send.call_count == 5


def test_login_page_sets_csrf_cookie(client: TestClient) -> None:
    """GET /login issues a csrf_token cookie so subsequent POSTs can match."""
    response = client.get("/login")
    assert "csrf_token" in response.cookies


@patch("odin.main.send_magic_link")
def test_send_link_rejects_mismatched_csrf(mock_send: MagicMock, client: TestClient) -> None:
    """POST with a CSRF form value that does not match the cookie returns 403."""
    client.cookies.set("csrf_token", "real-token")
    response = client.post(
        "/auth/send-link",
        data={"email": "user@example.com", "csrf_token": "tampered"},
    )
    assert response.status_code == 403
    mock_send.assert_not_called()


def test_logout_via_get_is_method_not_allowed(client: TestClient) -> None:
    """Logout is now POST-only to defend against link-based CSRF."""
    response = client.get("/auth/logout", follow_redirects=False)
    assert response.status_code == 405


def test_auth_verify_sets_session_cookie_and_redirects(client: TestClient) -> None:
    """GET /auth/verify with a valid token sets odin_session and redirects to /."""
    token = _auth.generate_magic_token("user@example.com", _TEST_SECRET)
    response = client.get(f"/auth/verify?token={token}", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert "odin_session" in response.cookies


def test_auth_verify_captures_login_ip_into_session(client: TestClient) -> None:
    """The /auth/verify response stores the link-clicker's IP in the session payload."""
    token = _auth.generate_magic_token("user@example.com", _TEST_SECRET)
    response = client.get(f"/auth/verify?token={token}", follow_redirects=False)
    cookie = response.cookies.get("odin_session")
    assert cookie is not None
    session = _auth.verify_session_value(cookie, _TEST_SECRET)
    assert session.email == "user@example.com"
    # Starlette's TestClient defaults the client host to "testclient"; we just want a value.
    assert session.ip


def test_status_bar_renders_email_and_ip_for_authenticated_pages(client: TestClient) -> None:
    """The base layout's status bar shows PILOT email and NODE IP when signed in."""
    session = _auth.create_session_value("user@example.com", _TEST_SECRET, ip="203.0.113.5")
    response = client.get("/dashboard", cookies={"odin_session": session})
    assert response.status_code == 200
    body = response.text
    assert "status-bar" in body
    assert "PILOT" in body
    assert "user@example.com" in body
    assert "NODE" in body
    assert "203.0.113.5" in body


def test_status_bar_absent_for_anonymous_pages(client: TestClient) -> None:
    """Status bar is hidden when no session cookie is present."""
    response = client.get("/login")
    assert response.status_code == 200
    assert "status-bar" not in response.text
    assert "PILOT" not in response.text


def test_auth_verify_invalid_token_renders_error(client: TestClient) -> None:
    """GET /auth/verify with a bad token renders an error on the login page."""
    response = client.get("/auth/verify?token=garbage.token")
    assert response.status_code == 200
    assert "Invalid or expired" in response.text


def test_auth_logout_clears_session_and_redirects(client: TestClient) -> None:
    """POST /auth/logout deletes the session cookie and redirects to /."""
    csrf = _seed_csrf(client)
    response = client.post("/auth/logout", data=csrf, follow_redirects=False)
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


def test_dashboard_signout_uses_post_form(client: TestClient) -> None:
    """Sign out on the dashboard is a POST form, not a GET link, since /auth/logout is POST-only."""
    session = _auth.create_session_value("user@example.com", _TEST_SECRET)
    response = client.get("/dashboard", cookies={"odin_session": session})
    assert response.status_code == 200
    assert 'href="/auth/logout"' not in response.text
    assert 'action="/auth/logout"' in response.text


def test_privacy_page_renders(client: TestClient) -> None:
    """GET /privacy returns the privacy policy with key disclosures."""
    response = client.get("/privacy")
    assert response.status_code == 200
    body = response.text
    assert "Privacy" in body
    assert "Anthropic" in body
    assert "SearXNG" in body or "search engines" in body
    assert "odin@odinseye.info" in body


def test_terms_page_renders(client: TestClient) -> None:
    """GET /terms returns the terms of service."""
    response = client.get("/terms")
    assert response.status_code == 200
    body = response.text
    assert "Terms" in body
    assert "odin@odinseye.info" in body


def test_footer_links_to_privacy_and_terms(client: TestClient) -> None:
    """The shared footer exposes privacy and terms links."""
    response = client.get("/")
    assert response.status_code == 200
    assert 'href="/privacy"' in response.text
    assert 'href="/terms"' in response.text


def test_disclosure_banner_shown_on_first_visit(client: TestClient) -> None:
    """Index renders the disclosure banner when odin_seen_notice cookie is absent."""
    response = client.get("/", cookies={})
    assert response.status_code == 200
    assert 'id="disclosure-banner"' in response.text
    assert "Anthropic" in response.text
    assert 'action="/notice/dismiss"' in response.text


def test_disclosure_banner_hidden_when_cookie_set(client: TestClient) -> None:
    """Index omits the banner once the user has dismissed it."""
    response = client.get("/", cookies={"odin_seen_notice": "1"})
    assert response.status_code == 200
    assert 'id="disclosure-banner"' not in response.text


def test_dismiss_notice_sets_cookie_and_redirects(client: TestClient) -> None:
    """POST /notice/dismiss sets the odin_seen_notice cookie and redirects to referer or home."""
    response = client.post("/notice/dismiss", follow_redirects=False)
    assert response.status_code == 303
    set_cookie = response.headers.get("set-cookie", "")
    assert "odin_seen_notice=1" in set_cookie
    assert "Max-Age=" in set_cookie


def test_account_delete_clears_data_and_logs_out(
    client: TestClient, mock_valkey: MagicMock
) -> None:
    """POST /account/delete: 303 to /, session cookie cleared, store.delete_user called."""
    email = "user@example.com"
    session = _auth.create_session_value(email, _TEST_SECRET)
    mock_valkey.delete = AsyncMock(return_value=1)
    mock_valkey.scan_iter = MagicMock(return_value=_async_iter([b"rate:user:abc:2026-05-07"]))
    client.cookies.set("odin_session", session)
    csrf = _seed_csrf(client)

    response = client.post(
        "/account/delete",
        data={"email": email, **csrf},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/"
    set_cookie = response.headers.get("set-cookie", "")
    assert "odin_session=" in set_cookie
    mock_valkey.delete.assert_awaited()


def test_account_delete_rejects_email_mismatch(client: TestClient) -> None:
    """Submitting a non-matching email returns 400."""
    session = _auth.create_session_value("user@example.com", _TEST_SECRET)
    client.cookies.set("odin_session", session)
    csrf = _seed_csrf(client)
    response = client.post(
        "/account/delete",
        data={"email": "wrong@example.com", **csrf},
        follow_redirects=False,
    )
    assert response.status_code == 400


def test_account_delete_rejects_missing_csrf(client: TestClient) -> None:
    """Without a matching CSRF token the endpoint returns 403."""
    session = _auth.create_session_value("user@example.com", _TEST_SECRET)
    client.cookies.set("odin_session", session)
    client.cookies.set("csrf_token", "right")
    response = client.post(
        "/account/delete",
        data={"csrf_token": "wrong", "email": "user@example.com"},
    )
    assert response.status_code == 403


def test_account_delete_rejects_unauthenticated(client: TestClient) -> None:
    """Without a session cookie the endpoint redirects to /login."""
    csrf = _seed_csrf(client)
    response = client.post(
        "/account/delete",
        data={"email": "user@example.com", **csrf},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "/login" in response.headers["location"]


def test_dashboard_shows_delete_account_form(client: TestClient) -> None:
    """Dashboard renders the delete-account form for authenticated users."""
    session = _auth.create_session_value("user@example.com", _TEST_SECRET)
    response = client.get("/dashboard", cookies={"odin_session": session})
    assert response.status_code == 200
    assert 'action="/account/delete"' in response.text

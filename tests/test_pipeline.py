"""Tests for the profile pipeline."""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from odin import pipeline
from odin.models import Assessment, Profile
from odin.search import SearchAggregator, SearchResult


@dataclass(frozen=True)
class _FakeFetcher:
    """Minimal PageFetcher stub used to exercise build_profile in isolation."""

    async def fetch_pages(self, urls: list[str]) -> dict[str, str]:
        return dict.fromkeys(urls, "")


@dataclass(frozen=True)
class _FakeBackend:
    """Minimal SearchBackend stub that delegates to a supplied search function."""

    search_fn: Callable[[str], Awaitable[list[SearchResult]]]
    name: str = "fake"
    timeout_seconds: float = 5.0

    async def search(self, query: str) -> list[SearchResult]:
        return await self.search_fn(query)


async def test_pipeline_bounds_search_concurrency() -> None:
    """build_profile should cap in-flight backend.search calls at SEARCH_QUERY_CONCURRENCY."""
    inflight = 0
    max_inflight = 0

    async def fake_search(q: str) -> list[SearchResult]:
        nonlocal inflight, max_inflight
        inflight += 1
        max_inflight = max(max_inflight, inflight)
        await asyncio.sleep(0.05)
        inflight -= 1
        return [SearchResult(url=f"https://e/{q}", title=q, content="", engines=["x"])]

    queries = [f"q{i}" for i in range(6)]
    anthropic = MagicMock()
    profile = MagicMock()
    profile.name = "n"

    with (
        patch.object(pipeline.claude, "categorize", AsyncMock(return_value="other")),
        patch.object(pipeline.claude, "generate_queries", AsyncMock(return_value=queries)),
        patch.object(pipeline.claude, "select_urls", AsyncMock(return_value=[])),
        patch.object(pipeline.claude, "synthesize", AsyncMock(return_value=profile)),
        patch.object(pipeline.claude, "assess", AsyncMock(side_effect=Exception("skip"))),
    ):
        async for _ in pipeline.build_profile(
            "foo",
            SearchAggregator(backends=(_FakeBackend(fake_search),)),
            anthropic,
            _FakeFetcher(),
        ):
            pass

    assert max_inflight <= pipeline.SEARCH_QUERY_CONCURRENCY
    assert max_inflight >= 2, "sanity: the test should actually exercise concurrency"


async def test_gather_search_results_bounds_concurrency() -> None:
    """_gather_search_results caps in-flight backend.search calls at SEARCH_QUERY_CONCURRENCY.

    Same guarantee as test_pipeline_bounds_search_concurrency, aimed directly
    at the extracted function rather than driven through the whole pipeline.
    """
    inflight = 0
    max_inflight = 0

    async def fake_search(q: str) -> list[SearchResult]:
        nonlocal inflight, max_inflight
        inflight += 1
        max_inflight = max(max_inflight, inflight)
        await asyncio.sleep(0.05)
        inflight -= 1
        return [SearchResult(url=f"https://e/{q}", title=q, content="", engines=["x"])]

    queries = [f"q{i}" for i in range(6)]

    await pipeline._gather_search_results(queries, _FakeBackend(fake_search))  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]

    assert max_inflight <= pipeline.SEARCH_QUERY_CONCURRENCY
    assert max_inflight >= 2, "sanity: the test should actually exercise concurrency"


async def test_gather_search_results_merges_duplicates_across_queries() -> None:
    """Results that surface from more than one query are merged, not duplicated.

    merge_results dedupes by URL in first-seen order and unions engines —
    pin that _gather_search_results actually feeds it the per-query batches
    in query order, so a result every query finds keeps its first slot and
    accumulates every engine that found it.
    """

    async def fake_search(q: str) -> list[SearchResult]:
        return [
            SearchResult(url="https://shared.example", title="Shared", content="c", engines=[q]),
            SearchResult(url=f"https://only/{q}", title=q, content="c", engines=[q]),
        ]

    queries = ["q0", "q1", "q2"]

    results = await pipeline._gather_search_results(queries, _FakeBackend(fake_search))  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]

    urls = [result.url for result in results]
    assert urls == [
        "https://shared.example",
        "https://only/q0",
        "https://only/q1",
        "https://only/q2",
    ]
    shared = results[0]
    assert shared.engines == ["q0", "q1", "q2"]


def _make_tracing_pipeline_doubles() -> tuple[
    list[str],
    dict[str, object],
    type,
    Callable[[str], Awaitable[list[SearchResult]]],
]:
    """Build doubles that record every claude/search/fetcher call into a shared trace."""
    trace: list[str] = []

    async def trace_categorize(*_args: object, **_kw: object) -> str:
        trace.append("call:categorize")
        return "other"

    async def trace_generate_queries(*_args: object, **_kw: object) -> list[str]:
        trace.append("call:generate_queries")
        return ["q1"]

    async def trace_select_urls(*_args: object, **_kw: object) -> list[str]:
        trace.append("call:select_urls")
        return ["https://e/1"]

    async def trace_synthesize(*_args: object, **_kw: object) -> Profile:
        trace.append("call:synthesize")
        return Profile(
            name="n",
            category="other",
            summary="s",
            highlights=[],
            lowlights=[],
            timeline=[],
            citations=[],
        )

    async def trace_assess(*_args: object, **_kw: object) -> Assessment:
        trace.append("call:assess")
        return Assessment(
            public_sentiment=0.0,
            subject_political_bias=0.0,
            source_political_bias=0.0,
            law_chaos=0.0,
            good_evil=0.0,
            caveats=[],
        )

    async def trace_search(q: str) -> list[SearchResult]:
        trace.append("call:search")
        return [SearchResult(url=f"https://e/{q}", title=q, content="", engines=["x"])]

    @dataclass(frozen=True)
    class _TraceFetcher:
        async def fetch_pages(self, urls: list[str]) -> dict[str, str]:
            trace.append("call:fetch_pages")
            return dict.fromkeys(urls, "body")

    doubles: dict[str, object] = {
        "categorize": trace_categorize,
        "generate_queries": trace_generate_queries,
        "select_urls": trace_select_urls,
        "synthesize": trace_synthesize,
        "assess": trace_assess,
    }
    return trace, doubles, _TraceFetcher, trace_search


async def test_pipeline_emits_synthesizing_and_assessing_events_at_phase_boundaries() -> None:
    """Yield synthesizing and assessing at phase boundaries.

    `synthesizing` fires between fetch and synthesize; `assessing` fires between
    synthesize and assess, so the UI can show progress during the long Sonnet calls.
    """
    trace, doubles, fetcher_cls, search_fn = _make_tracing_pipeline_doubles()
    with (
        patch.object(pipeline.claude, "categorize", side_effect=doubles["categorize"]),
        patch.object(pipeline.claude, "generate_queries", side_effect=doubles["generate_queries"]),
        patch.object(pipeline.claude, "select_urls", side_effect=doubles["select_urls"]),
        patch.object(pipeline.claude, "synthesize", side_effect=doubles["synthesize"]),
        patch.object(pipeline.claude, "assess", side_effect=doubles["assess"]),
    ):
        events: list[str] = []
        async for ev in pipeline.build_profile(
            "foo", SearchAggregator(backends=(_FakeBackend(search_fn),)), MagicMock(), fetcher_cls()
        ):
            trace.append(f"yield:{ev.stage}")
            events.append(ev.stage)

    assert events == [
        "categorized",
        "queries",
        "searching",
        "fetching",
        "synthesizing",
        "profile",
        "assessing",
        "assessment",
    ]
    assert trace.index("yield:synthesizing") > trace.index("call:fetch_pages")
    assert trace.index("yield:synthesizing") < trace.index("call:synthesize")
    assert trace.index("yield:assessing") > trace.index("call:synthesize")
    assert trace.index("yield:assessing") < trace.index("call:assess")


@dataclass(frozen=True)
class _EmptyFetcher:
    """Fetcher that always returns empty content — simulates all pages failing."""

    async def fetch_pages(self, urls: list[str]) -> dict[str, str]:
        return dict.fromkeys(urls, "")


async def test_pipeline_yields_service_unavailable_when_all_fetched_content_is_empty() -> None:
    """When every fetched page returns empty content, pipeline yields service_unavailable.

    This guards against handing Claude an empty context and letting it fabricate
    an answer from its priors instead of real sources.
    """

    async def fake_search(_q: str) -> list[SearchResult]:
        return [SearchResult(url="https://example.com", title="t", content="snippet")]

    with (
        patch.object(pipeline.claude, "categorize", AsyncMock(return_value="other")),
        patch.object(pipeline.claude, "generate_queries", AsyncMock(return_value=["q1"])),
        patch.object(
            pipeline.claude, "select_urls", AsyncMock(return_value=["https://example.com"])
        ),
        patch.object(pipeline.claude, "synthesize") as mock_synth,
    ):
        stages = [
            ev.stage
            async for ev in pipeline.build_profile(
                "foo",
                SearchAggregator(backends=(_FakeBackend(fake_search),)),
                MagicMock(),
                _EmptyFetcher(),
            )
        ]

    assert "service_unavailable" in stages
    mock_synth.assert_not_called()


async def test_pipeline_filters_disallowed_urls_before_select(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Search results with blocked extensions or blocked domains are stripped before select_urls."""
    monkeypatch.setattr(pipeline.settings, "url_domain_blocklist", ("bit.ly",))

    async def fake_search(_q: str) -> list[SearchResult]:
        return [
            SearchResult(url="https://example.com/article", title="ok"),
            SearchResult(url="https://example.com/whitepaper.pdf", title="pdf"),
            SearchResult(url="https://bit.ly/abc123", title="short"),
            SearchResult(url="https://example.org/page", title="ok2"),
        ]

    received: list[list[SearchResult]] = []

    async def capture_select_urls(
        _client: object, _query: str, results: list[SearchResult]
    ) -> list[str]:
        received.append(results)
        return [r.url for r in results]

    profile = Profile(
        name="n",
        category="other",
        summary="s",
        highlights=[],
        lowlights=[],
        timeline=[],
        citations=[],
    )

    with (
        patch.object(pipeline.claude, "categorize", AsyncMock(return_value="other")),
        patch.object(pipeline.claude, "generate_queries", AsyncMock(return_value=["q1"])),
        patch.object(pipeline.claude, "select_urls", side_effect=capture_select_urls),
        patch.object(pipeline.claude, "synthesize", AsyncMock(return_value=profile)),
        patch.object(pipeline.claude, "assess", AsyncMock(side_effect=Exception("skip"))),
    ):
        async for _ in pipeline.build_profile(
            "foo",
            SearchAggregator(backends=(_FakeBackend(fake_search),)),
            MagicMock(),
            _FakeFetcher(),
        ):
            pass

    assert len(received) == 1
    forwarded = [r.url for r in received[0]]
    assert forwarded == ["https://example.com/article", "https://example.org/page"]


def _profile_double() -> Profile:
    return Profile(
        name="n",
        category="other",
        summary="s",
        highlights=[],
        lowlights=[],
        timeline=[],
        citations=[],
    )


async def test_pipeline_names_backends_that_contributed_no_results() -> None:
    """The searching event names backends absent from the merged results' provenance.

    A backend can come up empty because it errored, timed out, or genuinely had
    nothing relevant — the aggregator does not distinguish these (and shouldn't
    have to: see _guarded). The user-facing message only needs the fact a reader
    cares about — which backends shaped this profile — not a guess at why one
    didn't.
    """

    async def brave_search(_q: str) -> list[SearchResult]:
        return [SearchResult(url="https://example.com/a", title="a", engines=["brave"])]

    async def wikipedia_search(_q: str) -> list[SearchResult]:
        return []

    aggregator = SearchAggregator(
        backends=(
            _FakeBackend(brave_search, name="brave"),
            _FakeBackend(wikipedia_search, name="wikipedia"),
        )
    )

    with (
        patch.object(pipeline.claude, "categorize", AsyncMock(return_value="other")),
        patch.object(pipeline.claude, "generate_queries", AsyncMock(return_value=["q1", "q2"])),
        patch.object(pipeline.claude, "select_urls", AsyncMock(return_value=[])),
        patch.object(pipeline.claude, "synthesize", AsyncMock(return_value=_profile_double())),
        patch.object(pipeline.claude, "assess", AsyncMock(side_effect=Exception("skip"))),
    ):
        events = [
            ev
            async for ev in pipeline.build_profile("foo", aggregator, MagicMock(), _FakeFetcher())
        ]

    searching = next(ev for ev in events if ev.stage == "searching")
    assert searching.data["missing_backends"] == ["wikipedia"]


async def test_pipeline_reports_no_missing_backends_when_all_contribute() -> None:
    """When every configured backend's results survive into the merged set, nothing is missing."""

    async def brave_search(_q: str) -> list[SearchResult]:
        return [SearchResult(url="https://example.com/a", title="a", engines=["brave"])]

    async def wikipedia_search(_q: str) -> list[SearchResult]:
        return [SearchResult(url="https://example.com/b", title="b", engines=["wikipedia"])]

    aggregator = SearchAggregator(
        backends=(
            _FakeBackend(brave_search, name="brave"),
            _FakeBackend(wikipedia_search, name="wikipedia"),
        )
    )

    with (
        patch.object(pipeline.claude, "categorize", AsyncMock(return_value="other")),
        patch.object(pipeline.claude, "generate_queries", AsyncMock(return_value=["q1"])),
        patch.object(pipeline.claude, "select_urls", AsyncMock(return_value=[])),
        patch.object(pipeline.claude, "synthesize", AsyncMock(return_value=_profile_double())),
        patch.object(pipeline.claude, "assess", AsyncMock(side_effect=Exception("skip"))),
    ):
        events = [
            ev
            async for ev in pipeline.build_profile("foo", aggregator, MagicMock(), _FakeFetcher())
        ]

    searching = next(ev for ev in events if ev.stage == "searching")
    assert searching.data["missing_backends"] == []

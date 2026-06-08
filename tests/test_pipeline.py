"""Tests for the profile pipeline."""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from odin import pipeline
from odin.models import Assessment, Connection, Profile
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


def _draft_profile() -> Profile:
    return Profile(
        name="draft",
        category="other",
        summary="draft summary",
        highlights=[],
        lowlights=[],
        timeline=[],
        citations=[],
    )


def _final_profile() -> Profile:
    return Profile(
        name="final",
        category="other",
        summary="final summary",
        highlights=[],
        lowlights=[],
        timeline=[],
        citations=[],
    )


def _constant_double[T](trace: list[str], label: str, value: T) -> Callable[..., Awaitable[T]]:
    """Build an async double that records `call:{label}` and returns a fixed value.

    Several deep-pipeline doubles do nothing but trace their call and hand
    back a precomputed value — factored out so _make_deep_pipeline_doubles
    doesn't repeat that shape per stage and stay under the complexity limit.
    """

    async def _double(*_args: object, **_kw: object) -> T:
        trace.append(f"call:{label}")
        return value

    return _double


def _make_deep_pipeline_doubles(
    gap_queries: list[str],
) -> tuple[
    list[str],
    dict[str, object],
    type,
    Callable[[str], Awaitable[list[SearchResult]]],
]:
    """Build doubles for the deep pipeline; gap_queries controls identify_gaps' return.

    The synthesize double tells draft from final apart by call order — the
    first call returns a draft profile, every later call returns the final
    one — so tests can pin that exactly two synthesis calls happen no matter
    how many follow-up rounds run.
    """
    trace: list[str] = []
    synth_calls = 0

    async def trace_select_urls(
        _client: object, _query: str, results: list[SearchResult]
    ) -> list[str]:
        trace.append("call:select_urls")
        return [r.url for r in results]

    async def trace_synthesize(
        _client: object,
        _query: str,
        _category: str,
        _content: dict[str, str],
        _sources: list[SearchResult],
    ) -> Profile:
        nonlocal synth_calls
        synth_calls += 1
        trace.append("call:synthesize")
        return _draft_profile() if synth_calls == 1 else _final_profile()

    async def trace_search(q: str) -> list[SearchResult]:
        trace.append(f"call:search:{q}")
        return [SearchResult(url=f"https://e/{q}", title=q, content="", engines=["x"])]

    @dataclass(frozen=True)
    class _TraceFetcher:
        async def fetch_pages(self, urls: list[str]) -> dict[str, str]:
            trace.append("call:fetch_pages")
            return dict.fromkeys(urls, "body")

    empty_connections: list[Connection] = []
    assessment = Assessment(
        public_sentiment=0.0,
        subject_political_bias=0.0,
        source_political_bias=0.0,
        law_chaos=0.0,
        good_evil=0.0,
        caveats=[],
    )
    doubles: dict[str, object] = {
        "categorize": _constant_double(trace, "categorize", "other"),
        "generate_queries": _constant_double(trace, "generate_queries", ["initial query"]),
        "select_urls": trace_select_urls,
        "synthesize": trace_synthesize,
        "identify_gaps": AsyncMock(return_value=gap_queries),
        "find_connections": _constant_double(trace, "find_connections", empty_connections),
        "assess": _constant_double(trace, "assess", assessment),
    }
    return trace, doubles, _TraceFetcher, trace_search


async def test_deep_profile_runs_followup_rounds_and_synthesizes_exactly_twice() -> None:
    """build_deep_profile drafts, identifies gaps, runs bounded rounds, then synthesizes once more.

    Exactly two synthesis calls happen — draft, then final — no matter how
    many follow-up rounds the gap analysis drives. That two-call shape is what
    keeps deep mode's extra Sonnet cost predictable and bounded.
    """
    trace, doubles, fetcher_cls, search_fn = _make_deep_pipeline_doubles(["gap one", "gap two"])
    with (
        patch.object(pipeline.claude, "categorize", side_effect=doubles["categorize"]),
        patch.object(pipeline.claude, "generate_queries", side_effect=doubles["generate_queries"]),
        patch.object(pipeline.claude, "select_urls", side_effect=doubles["select_urls"]),
        patch.object(pipeline.claude, "synthesize", side_effect=doubles["synthesize"]),
        patch.object(pipeline.claude, "identify_gaps", side_effect=doubles["identify_gaps"]),
        patch.object(pipeline.claude, "find_connections", side_effect=doubles["find_connections"]),
        patch.object(pipeline.claude, "assess", side_effect=doubles["assess"]),
    ):
        events = [
            ev
            async for ev in pipeline.build_deep_profile(
                "foo",
                SearchAggregator(backends=(_FakeBackend(search_fn),)),
                MagicMock(),
                fetcher_cls(),
            )
        ]

    stages = [ev.stage for ev in events]
    assert stages == [
        "categorized",
        "queries",
        "searching",
        "fetching",
        "draft_synthesizing",
        "deep_gap_analysis",
        "deep_searching",
        "deep_fetching",
        "deep_searching",
        "deep_fetching",
        "deep_connecting",
        "connections",
        "synthesizing",
        "profile",
        "assessing",
        "assessment",
    ]
    assert trace.count("call:synthesize") == 2
    gap_event = next(ev for ev in events if ev.stage == "deep_gap_analysis")
    assert gap_event.data["queries"] == ["gap one", "gap two"]
    deep_searching = [ev for ev in events if ev.stage == "deep_searching"]
    assert [ev.data["round"] for ev in deep_searching] == [1, 2]
    assert [ev.data["query"] for ev in deep_searching] == ["gap one", "gap two"]


async def test_deep_profile_skips_followup_rounds_when_no_gaps_identified() -> None:
    """An empty gap list goes straight from gap analysis to final synthesis.

    identify_gaps returning [] is the loop's "draft already looks
    comprehensive" signal — no extra search, fetch, or round events follow it.
    """
    trace, doubles, fetcher_cls, search_fn = _make_deep_pipeline_doubles([])
    with (
        patch.object(pipeline.claude, "categorize", side_effect=doubles["categorize"]),
        patch.object(pipeline.claude, "generate_queries", side_effect=doubles["generate_queries"]),
        patch.object(pipeline.claude, "select_urls", side_effect=doubles["select_urls"]),
        patch.object(pipeline.claude, "synthesize", side_effect=doubles["synthesize"]),
        patch.object(pipeline.claude, "identify_gaps", side_effect=doubles["identify_gaps"]),
        patch.object(pipeline.claude, "find_connections", side_effect=doubles["find_connections"]),
        patch.object(pipeline.claude, "assess", side_effect=doubles["assess"]),
    ):
        events = [
            ev
            async for ev in pipeline.build_deep_profile(
                "foo",
                SearchAggregator(backends=(_FakeBackend(search_fn),)),
                MagicMock(),
                fetcher_cls(),
            )
        ]

    stages = [ev.stage for ev in events]
    assert "deep_searching" not in stages
    assert "deep_fetching" not in stages
    assert stages.index("deep_gap_analysis") < stages.index("synthesizing")
    assert trace.count("call:synthesize") == 2
    assert sum(1 for entry in trace if entry.startswith("call:search:")) == 1


async def test_deep_profile_caps_followup_rounds_at_the_hard_limit() -> None:
    """The loop never runs more rounds than DEEP_MODE_MAX_ROUNDS, even if asked to.

    The identify_gaps tool schema already caps queries at DEEP_MODE_MAX_ROUNDS,
    but the loop must not simply trust that — it slices to the cap so a schema
    violation can't blow the cost bound this slice exists to guarantee.
    """
    too_many = [f"gap {i}" for i in range(pipeline.DEEP_MODE_MAX_ROUNDS + 2)]
    trace, doubles, fetcher_cls, search_fn = _make_deep_pipeline_doubles(too_many)
    with (
        patch.object(pipeline.claude, "categorize", side_effect=doubles["categorize"]),
        patch.object(pipeline.claude, "generate_queries", side_effect=doubles["generate_queries"]),
        patch.object(pipeline.claude, "select_urls", side_effect=doubles["select_urls"]),
        patch.object(pipeline.claude, "synthesize", side_effect=doubles["synthesize"]),
        patch.object(pipeline.claude, "identify_gaps", side_effect=doubles["identify_gaps"]),
        patch.object(pipeline.claude, "find_connections", side_effect=doubles["find_connections"]),
        patch.object(pipeline.claude, "assess", side_effect=doubles["assess"]),
    ):
        events = [
            ev
            async for ev in pipeline.build_deep_profile(
                "foo",
                SearchAggregator(backends=(_FakeBackend(search_fn),)),
                MagicMock(),
                fetcher_cls(),
            )
        ]

    deep_searching = [ev for ev in events if ev.stage == "deep_searching"]
    assert len(deep_searching) == pipeline.DEEP_MODE_MAX_ROUNDS
    assert [ev.data["round"] for ev in deep_searching] == list(
        range(1, pipeline.DEEP_MODE_MAX_ROUNDS + 1)
    )
    assert trace.count("call:synthesize") == 2


async def test_deep_profile_skips_a_round_whose_results_all_dedupe_against_existing_content() -> (
    None
):
    """A follow-up round that turns up nothing new past dedup is skipped, not run anyway.

    "stale gap" resurfaces the exact URL the initial pass already fetched, so
    nothing survives the dedupe check — its round produces no events and no
    extra select/fetch calls, and the loop continues to "fresh gap".
    """
    trace, doubles, fetcher_cls, _unused_search = _make_deep_pipeline_doubles(
        ["stale gap", "fresh gap"]
    )

    async def search_fn(q: str) -> list[SearchResult]:
        trace.append(f"call:search:{q}")
        url = "https://e/initial query" if q == "stale gap" else f"https://e/{q}"
        return [SearchResult(url=url, title=q, content="", engines=["x"])]

    with (
        patch.object(pipeline.claude, "categorize", side_effect=doubles["categorize"]),
        patch.object(pipeline.claude, "generate_queries", side_effect=doubles["generate_queries"]),
        patch.object(pipeline.claude, "select_urls", side_effect=doubles["select_urls"]),
        patch.object(pipeline.claude, "synthesize", side_effect=doubles["synthesize"]),
        patch.object(pipeline.claude, "identify_gaps", side_effect=doubles["identify_gaps"]),
        patch.object(pipeline.claude, "find_connections", side_effect=doubles["find_connections"]),
        patch.object(pipeline.claude, "assess", side_effect=doubles["assess"]),
    ):
        events = [
            ev
            async for ev in pipeline.build_deep_profile(
                "foo",
                SearchAggregator(backends=(_FakeBackend(search_fn),)),
                MagicMock(),
                fetcher_cls(),
            )
        ]

    deep_searching = [ev for ev in events if ev.stage == "deep_searching"]
    assert [ev.data["query"] for ev in deep_searching] == ["fresh gap"]
    assert sum(1 for ev in events if ev.stage == "deep_fetching") == 1
    assert trace.count("call:synthesize") == 2


async def test_deep_profile_final_synthesis_sees_merged_sources_and_content() -> None:
    """The final synthesize call receives the union of initial and follow-up content.

    Running the extra rounds is only worth it if the final pass actually sees
    what they found — pin that the merge actually reaches the last synthesize
    call, not just an internal accumulator nothing reads.
    """
    synthesize_calls: list[tuple[dict[str, str], list[SearchResult]]] = []

    async def capturing_synthesize(
        _client: object,
        _query: str,
        _category: str,
        content: dict[str, str],
        sources: list[SearchResult],
    ) -> Profile:
        synthesize_calls.append((dict(content), list(sources)))
        return _draft_profile() if len(synthesize_calls) == 1 else _final_profile()

    _trace, doubles, fetcher_cls, search_fn = _make_deep_pipeline_doubles(["gap query"])
    with (
        patch.object(pipeline.claude, "categorize", side_effect=doubles["categorize"]),
        patch.object(pipeline.claude, "generate_queries", side_effect=doubles["generate_queries"]),
        patch.object(pipeline.claude, "select_urls", side_effect=doubles["select_urls"]),
        patch.object(pipeline.claude, "synthesize", side_effect=capturing_synthesize),
        patch.object(pipeline.claude, "identify_gaps", side_effect=doubles["identify_gaps"]),
        patch.object(pipeline.claude, "find_connections", side_effect=doubles["find_connections"]),
        patch.object(pipeline.claude, "assess", side_effect=doubles["assess"]),
    ):
        async for _ in pipeline.build_deep_profile(
            "foo",
            SearchAggregator(backends=(_FakeBackend(search_fn),)),
            MagicMock(),
            fetcher_cls(),
        ):
            pass

    assert len(synthesize_calls) == 2
    draft_content, draft_sources = synthesize_calls[0]
    final_content, final_sources = synthesize_calls[1]
    assert set(draft_content) == {"https://e/initial query"}
    assert set(final_content) == {"https://e/initial query", "https://e/gap query"}
    assert {s.url for s in final_sources} == {"https://e/initial query", "https://e/gap query"}
    assert {s.url for s in draft_sources} <= {s.url for s in final_sources}


async def test_deep_profile_runs_connection_pass_with_merged_sources_before_final_synthesis() -> (
    None
):
    """The connection pass runs once, after the gap rounds, on the full merged source set.

    It must see what the final synthesis sees — connections found only from
    the initial pass would miss whatever the follow-up rounds turned up, and
    citing sources the final profile never drew from would be its own kind of
    ungrounded claim.
    """
    connection_calls: list[tuple[dict[str, str], list[SearchResult]]] = []

    async def capturing_find_connections(
        _client: object,
        _query: str,
        _category: str,
        content: dict[str, str],
        sources: list[SearchResult],
    ) -> list[Connection]:
        connection_calls.append((dict(content), list(sources)))
        return []

    _trace, doubles, fetcher_cls, search_fn = _make_deep_pipeline_doubles(["gap query"])
    with (
        patch.object(pipeline.claude, "categorize", side_effect=doubles["categorize"]),
        patch.object(pipeline.claude, "generate_queries", side_effect=doubles["generate_queries"]),
        patch.object(pipeline.claude, "select_urls", side_effect=doubles["select_urls"]),
        patch.object(pipeline.claude, "synthesize", side_effect=doubles["synthesize"]),
        patch.object(pipeline.claude, "identify_gaps", side_effect=doubles["identify_gaps"]),
        patch.object(pipeline.claude, "find_connections", side_effect=capturing_find_connections),
        patch.object(pipeline.claude, "assess", side_effect=doubles["assess"]),
    ):
        events = [
            ev
            async for ev in pipeline.build_deep_profile(
                "foo",
                SearchAggregator(backends=(_FakeBackend(search_fn),)),
                MagicMock(),
                fetcher_cls(),
            )
        ]

    stages = [ev.stage for ev in events]
    assert stages.index("deep_fetching") < stages.index("deep_connecting")
    assert stages.index("deep_connecting") < stages.index("connections")
    assert stages.index("connections") < stages.index("synthesizing")

    assert len(connection_calls) == 1
    content, sources = connection_calls[0]
    assert set(content) == {"https://e/initial query", "https://e/gap query"}
    assert {s.url for s in sources} == {"https://e/initial query", "https://e/gap query"}

    connecting_event = next(ev for ev in events if ev.stage == "deep_connecting")
    assert connecting_event.data["source_count"] == 2
    connections_event = next(ev for ev in events if ev.stage == "connections")
    assert connections_event.data["connections"] == []


async def test_deep_profile_skips_connection_pass_when_fewer_than_two_sources_gathered() -> None:
    """A single surviving source skips the connection pass entirely — no call, no events.

    "Cross-source" is meaningless with one source; spending a Sonnet call to
    confirm that would cost without ever returning anything, the same
    cost-consciousness `_run_followup_rounds` already applies when a round
    turns up nothing new.
    """
    trace, doubles, fetcher_cls, search_fn = _make_deep_pipeline_doubles([])
    with (
        patch.object(pipeline.claude, "categorize", side_effect=doubles["categorize"]),
        patch.object(pipeline.claude, "generate_queries", side_effect=doubles["generate_queries"]),
        patch.object(pipeline.claude, "select_urls", side_effect=doubles["select_urls"]),
        patch.object(pipeline.claude, "synthesize", side_effect=doubles["synthesize"]),
        patch.object(pipeline.claude, "identify_gaps", side_effect=doubles["identify_gaps"]),
        patch.object(pipeline.claude, "find_connections", side_effect=doubles["find_connections"]),
        patch.object(pipeline.claude, "assess", side_effect=doubles["assess"]),
    ):
        events = [
            ev
            async for ev in pipeline.build_deep_profile(
                "foo",
                SearchAggregator(backends=(_FakeBackend(search_fn),)),
                MagicMock(),
                fetcher_cls(),
            )
        ]

    stages = [ev.stage for ev in events]
    assert "deep_connecting" not in stages
    assert "connections" not in stages
    assert "call:find_connections" not in trace

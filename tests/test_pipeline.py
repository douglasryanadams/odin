"""Tests for the profile pipeline."""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from odin import pipeline
from odin.models import Assessment, Profile
from odin.search import SearchResult


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
            "foo", _FakeBackend(fake_search), anthropic, _FakeFetcher()
        ):
            pass

    assert max_inflight <= pipeline.SEARCH_QUERY_CONCURRENCY
    assert max_inflight >= 2, "sanity: the test should actually exercise concurrency"


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
            "foo", _FakeBackend(search_fn), MagicMock(), fetcher_cls()
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
            "foo", _FakeBackend(fake_search), MagicMock(), _FakeFetcher()
        ):
            pass

    assert len(received) == 1
    forwarded = [r.url for r in received[0]]
    assert forwarded == ["https://example.com/article", "https://example.org/page"]

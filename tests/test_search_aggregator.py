"""Tests for the search aggregator: cross-backend dedupe, engines union, graceful degradation."""

import asyncio
import time
from dataclasses import dataclass

from odin.search import SearchAggregator, SearchResult
from odin.search.aggregator import BackendOutcome, merge_results


@dataclass(frozen=True)
class _FakeBackend:
    """In-memory SearchBackend stub returning a fixed result list."""

    name: str
    results: list[SearchResult]
    timeout_seconds: float = 5.0
    delay: float = 0.0

    async def search(self, query: str) -> list[SearchResult]:  # noqa: ARG002
        if self.delay:
            await asyncio.sleep(self.delay)
        return list(self.results)


@dataclass(frozen=True)
class _RaisingBackend:
    """A backend whose search always raises, to exercise the aggregator's guard."""

    name: str = "boom"
    timeout_seconds: float = 5.0

    async def search(self, query: str) -> list[SearchResult]:  # noqa: ARG002
        msg = "backend down"
        raise RuntimeError(msg)


def _result(
    url: str, *, title: str = "t", content: str = "", engines: list[str] | None = None
) -> SearchResult:
    return SearchResult(url=url, title=title, content=content, engines=engines or [])


async def test_aggregator_dedupes_urls_across_backends() -> None:
    """The same URL returned by two backends collapses to a single result."""
    a = _FakeBackend(name="a", results=[_result("https://x/1", engines=["a"])])
    b = _FakeBackend(name="b", results=[_result("https://x/1", engines=["b"])])
    out = await SearchAggregator(backends=(a, b)).search("q")
    assert [r.url for r in out] == ["https://x/1"]


async def test_aggregator_unions_engines_for_shared_url() -> None:
    """When backends agree on a URL, their engines union (order-preserving, deduped)."""
    a = _FakeBackend(name="a", results=[_result("https://x/1", engines=["a"])])
    b = _FakeBackend(name="b", results=[_result("https://x/1", engines=["b"])])
    out = await SearchAggregator(backends=(a, b)).search("q")
    assert out[0].engines == ["a", "b"]


async def test_aggregator_backfills_empty_title_and_content() -> None:
    """First backend wins on order; an empty field is backfilled from a later backend."""
    a = _FakeBackend(
        name="a", results=[_result("https://x/1", title="", content="", engines=["a"])]
    )
    b = _FakeBackend(
        name="b", results=[_result("https://x/1", title="full", content="body", engines=["b"])]
    )
    out = await SearchAggregator(backends=(a, b)).search("q")
    assert out[0].title == "full"
    assert out[0].content == "body"


async def test_aggregator_returns_partial_results_when_a_backend_times_out() -> None:
    """A backend exceeding its timeout is dropped; fast backends return, within the timeout."""
    fast = _FakeBackend(name="fast", results=[_result("https://x/fast", engines=["fast"])])
    slow = _FakeBackend(
        name="slow", results=[_result("https://x/slow")], timeout_seconds=0.05, delay=5.0
    )
    start = time.monotonic()
    out = await SearchAggregator(backends=(fast, slow)).search("q")
    elapsed = time.monotonic() - start
    assert [r.url for r in out] == ["https://x/fast"]
    assert elapsed < 1.0, "the slow backend's timeout must bound aggregator wall-time"


async def test_aggregator_survives_a_backend_that_raises() -> None:
    """An exception from one backend is swallowed; other backends' results survive."""
    ok = _FakeBackend(name="ok", results=[_result("https://x/ok", engines=["ok"])])
    out = await SearchAggregator(backends=(ok, _RaisingBackend())).search("q")
    assert [r.url for r in out] == ["https://x/ok"]


async def test_aggregator_returns_empty_when_all_backends_fail() -> None:
    """If every backend raises or times out, the aggregator returns [] rather than raising."""
    out = await SearchAggregator(
        backends=(_RaisingBackend(name="b1"), _RaisingBackend(name="b2"))
    ).search("q")
    assert out == []


async def test_aggregator_with_no_backends_returns_empty() -> None:
    """A fail-closed empty backend set yields no results and does not raise."""
    assert await SearchAggregator(backends=()).search("q") == []


def test_merge_results_unions_engines_across_batches() -> None:
    """merge_results applies the same dedupe+union rule, across query batches (pipeline layer)."""
    batch1 = [_result("https://x/1", engines=["a"])]
    batch2 = [_result("https://x/1", engines=["b"]), _result("https://x/2", engines=["b"])]
    merged = merge_results([batch1, batch2])
    assert [r.url for r in merged] == ["https://x/1", "https://x/2"]
    assert merged[0].engines == ["a", "b"]


async def test_aggregator_records_success_outcome_per_backend() -> None:
    """Every backend that returns results reports a success outcome with its result count."""
    recorded: list[BackendOutcome] = []

    async def _record(outcome: BackendOutcome) -> None:
        recorded.append(outcome)

    a = _FakeBackend(name="a", results=[_result("https://x/1"), _result("https://x/2")])
    b = _FakeBackend(name="b", results=[_result("https://x/3")])
    await SearchAggregator(backends=(a, b), record_outcome=_record).search("q")

    by_name = {outcome.name: outcome for outcome in recorded}
    assert by_name["a"].outcome == "success"
    assert by_name["a"].result_count == 2
    assert by_name["b"].outcome == "success"
    assert by_name["b"].result_count == 1
    assert all(outcome.elapsed_seconds >= 0 for outcome in recorded)


async def test_aggregator_records_timeout_outcome() -> None:
    """A backend that exceeds its timeout reports a timeout outcome with zero results."""
    recorded: list[BackendOutcome] = []

    async def _record(outcome: BackendOutcome) -> None:
        recorded.append(outcome)

    slow = _FakeBackend(
        name="slow", results=[_result("https://x/slow")], timeout_seconds=0.05, delay=5.0
    )
    await SearchAggregator(backends=(slow,), record_outcome=_record).search("q")

    assert len(recorded) == 1
    assert recorded[0].outcome == "timeout"
    assert recorded[0].result_count == 0


async def test_aggregator_records_error_outcome() -> None:
    """A backend that raises reports an error outcome with zero results."""
    recorded: list[BackendOutcome] = []

    async def _record(outcome: BackendOutcome) -> None:
        recorded.append(outcome)

    await SearchAggregator(backends=(_RaisingBackend(name="boom"),), record_outcome=_record).search(
        "q"
    )

    assert len(recorded) == 1
    assert recorded[0].outcome == "error"
    assert recorded[0].result_count == 0

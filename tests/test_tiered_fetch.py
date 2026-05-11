"""Tests for ``TieredPageFetcher`` — composes curl_cffi (Tier 0) with Playwright (Tier 1).

These tests use fake tier implementations rather than real network calls; the
real-network behavior of each tier is covered by ``test_curl_fetch.py`` and
``test_fetch.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from odin.curl_fetch import CurlFetchResult
from odin.fetch import PageFetcher, TieredPageFetcher

_PLAYWRIGHT_MUST_NOT_RUN = "Playwright tier must not be invoked"


def _empty_call_log() -> list[list[str]]:
    """Typed factory so dataclass field inference stays strict-pyright clean."""
    return []


@dataclass(frozen=True)
class _FakeCurlFetcher:
    """Returns canned ``CurlFetchResult`` per URL, recording call order."""

    by_url: dict[str, CurlFetchResult]
    calls: list[list[str]] = field(default_factory=_empty_call_log)

    async def fetch_pages(self, urls: list[str]) -> dict[str, CurlFetchResult]:
        self.calls.append(list(urls))
        return {u: self.by_url[u] for u in urls}


@dataclass(frozen=True)
class _FakePlaywrightFetcher:
    """Returns canned strings per URL, recording every URL it was asked to fetch."""

    by_url: dict[str, str]
    calls: list[list[str]] = field(default_factory=_empty_call_log)

    async def fetch_pages(self, urls: list[str]) -> dict[str, str]:
        self.calls.append(list(urls))
        return {u: self.by_url[u] for u in urls}


@dataclass(frozen=True)
class _ExplodingPlaywrightFetcher:
    """Raises ``AssertionError`` on any access — guards the Tier-0-only happy path."""

    async def fetch_pages(self, urls: list[str]) -> dict[str, str]:
        raise AssertionError(_PLAYWRIGHT_MUST_NOT_RUN + f"; got {urls!r}")


async def test_tiered_skips_playwright_when_curl_succeeds() -> None:
    """Every URL succeeding in Tier 0 means Tier 1 is not even instantiated."""
    urls = ["http://a.test/x", "http://b.test/y"]
    curl = _FakeCurlFetcher(
        by_url={
            urls[0]: CurlFetchResult(text="content A", fall_back=False),
            urls[1]: CurlFetchResult(text="content B", fall_back=False),
        }
    )
    pw: PageFetcher = _ExplodingPlaywrightFetcher()
    fetcher = TieredPageFetcher(curl=curl, playwright=pw)

    result = await fetcher.fetch_pages(urls)

    assert result == {urls[0]: "content A", urls[1]: "content B"}


async def test_tiered_partial_fallback_routes_only_failed_urls_to_playwright() -> None:
    """Mixed batch: curl-success, curl-fail->pw-success, curl-fail->pw-fail."""
    urls = ["http://ok.test/a", "http://bot.test/b", "http://dead.test/c"]
    curl = _FakeCurlFetcher(
        by_url={
            urls[0]: CurlFetchResult(text="curl content", fall_back=False),
            urls[1]: CurlFetchResult(text="", fall_back=True),
            urls[2]: CurlFetchResult(text="", fall_back=True),
        }
    )
    pw = _FakePlaywrightFetcher(
        by_url={
            urls[1]: "playwright rescued b",
            urls[2]: "Error fetching URL: connection refused",
        }
    )
    fetcher = TieredPageFetcher(curl=curl, playwright=pw)

    result = await fetcher.fetch_pages(urls)

    assert pw.calls == [[urls[1], urls[2]]], "Playwright must only see fallback URLs"
    assert result[urls[0]] == "curl content"
    assert result[urls[1]] == "playwright rescued b"
    assert "Error" in result[urls[2]]


async def test_tiered_preserves_url_order_in_result() -> None:
    """Result dict iteration order matches the input order regardless of which tier won."""
    urls = ["http://a.test/", "http://b.test/", "http://c.test/", "http://d.test/"]
    curl = _FakeCurlFetcher(
        by_url={
            urls[0]: CurlFetchResult(text="A", fall_back=False),
            urls[1]: CurlFetchResult(text="", fall_back=True),
            urls[2]: CurlFetchResult(text="C", fall_back=False),
            urls[3]: CurlFetchResult(text="", fall_back=True),
        }
    )
    pw = _FakePlaywrightFetcher(by_url={urls[1]: "B", urls[3]: "D"})
    fetcher = TieredPageFetcher(curl=curl, playwright=pw)

    result = await fetcher.fetch_pages(urls)

    assert list(result.keys()) == urls
    assert list(result.values()) == ["A", "B", "C", "D"]


async def test_tiered_skips_curl_when_disabled() -> None:
    """Disabling curl_cffi (via constructor flag) routes everything through Playwright."""
    urls = ["http://a.test/"]
    curl = _FakeCurlFetcher(by_url={})
    pw = _FakePlaywrightFetcher(by_url={urls[0]: "pw only"})
    fetcher = TieredPageFetcher(curl=curl, playwright=pw, curl_enabled=False)

    result = await fetcher.fetch_pages(urls)

    assert curl.calls == [], "Curl tier must not be called when disabled"
    assert pw.calls == [urls]
    assert result == {urls[0]: "pw only"}


async def test_tiered_returns_empty_dict_for_empty_input() -> None:
    """A no-URL batch short-circuits before touching either tier."""
    curl = _FakeCurlFetcher(by_url={})
    pw: PageFetcher = _ExplodingPlaywrightFetcher()
    fetcher = TieredPageFetcher(curl=curl, playwright=pw)

    result = await fetcher.fetch_pages([])

    assert result == {}
    assert curl.calls == []

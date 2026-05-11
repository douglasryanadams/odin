"""Tests for the curl_cffi tier of the fetch pipeline.

These tests cover the pure ``should_fall_back`` predicate plus the
``CurlCffiPageFetcher`` against an in-process ``pytest-httpserver`` fixture.
Both pieces live in ``odin.curl_fetch``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from odin.curl_fetch import CurlCffiPageFetcher, should_fall_back

if TYPE_CHECKING:
    from pytest_httpserver import HTTPServer

_LONG_ARTICLE = (
    "<html><body><article><h1>Title</h1><p>"
    "This page has plenty of text content so trafilatura will recognize it as "
    "a real article and return a non-empty extraction. Filler keeps the body "
    "above trafilatura's minimum length: "
    + ("the quick brown fox jumps over the lazy dog. " * 30)
    + "</p></article></body></html>"
)

_CLOUDFLARE_INTERSTITIAL = (
    "<html><head><title>Just a moment...</title></head>"
    "<body><h1>Checking your browser before accessing the site.</h1>"
    "<p>This process is automatic. Your browser will redirect to your "
    "requested content shortly.</p></body></html>"
)

_ACCESS_DENIED = (
    "<html><head><title>Access Denied</title></head>"
    "<body><h1>Access Denied</h1><p>You don't have permission to access "
    "this resource on this server.</p></body></html>"
)

_ATTENTION_REQUIRED = (
    "<html><head><title>Attention Required! | Cloudflare</title></head>"
    "<body><p>Please verify you are human.</p></body></html>"
)

_HEAVY_HTML_NO_ARTICLE = "<html><body>" + ("<div>boilerplate noise </div>" * 400) + "</body></html>"

_CLEAN_EXTRACTION = "A clean article extraction with several hundred characters " * 6


def test_should_not_fall_back_on_clean_article() -> None:
    """200 + healthy extraction → no fallback."""
    assert should_fall_back(200, _LONG_ARTICLE, _CLEAN_EXTRACTION) is False


def test_should_fall_back_on_4xx_status() -> None:
    """403 from origin should always trigger fallback."""
    assert should_fall_back(403, _LONG_ARTICLE, _CLEAN_EXTRACTION) is True


def test_should_fall_back_on_5xx_status() -> None:
    """502 from origin should also trigger fallback."""
    assert should_fall_back(502, _LONG_ARTICLE, _CLEAN_EXTRACTION) is True


def test_should_fall_back_on_cloudflare_interstitial_regex() -> None:
    """A 200 response whose body matches the bot-wall regex falls back."""
    assert should_fall_back(200, _CLOUDFLARE_INTERSTITIAL, "short text") is True


def test_should_fall_back_on_access_denied_body() -> None:
    """'Access denied' phrase in the body triggers fallback."""
    assert should_fall_back(200, _ACCESS_DENIED, "short text") is True


def test_should_fall_back_on_attention_required_title() -> None:
    """'Attention Required' (Cloudflare's title for many challenges) triggers fallback."""
    assert should_fall_back(200, _ATTENTION_REQUIRED, "short text") is True


def test_should_fall_back_when_html_large_but_extraction_tiny() -> None:
    """Lots of HTML with essentially no article body looks like a bot wall."""
    assert should_fall_back(200, _HEAVY_HTML_NO_ARTICLE, "x" * 50) is True


def test_should_not_fall_back_when_both_html_and_extraction_short() -> None:
    """A genuinely tiny page (e.g. a JSON-API HTML wrapper) is not a bot wall."""
    tiny_html = "<html><body><p>ok</p></body></html>"
    assert should_fall_back(200, tiny_html, "ok") is False


async def test_curl_cffi_happy_path(httpserver: HTTPServer) -> None:
    """A well-formed HTML article is fetched and extracted, with no fallback flag."""
    httpserver.expect_request("/article").respond_with_data(_LONG_ARTICLE, content_type="text/html")
    url = httpserver.url_for("/article")

    fetcher = CurlCffiPageFetcher()
    results = await fetcher.fetch_pages([url])

    assert url in results
    assert results[url].fall_back is False
    assert "quick brown fox" in results[url].text


async def test_curl_cffi_marks_fallback_on_403(httpserver: HTTPServer) -> None:
    """A 403 response flags the result for fallback to Playwright."""
    httpserver.expect_request("/forbidden").respond_with_data(
        "<html><body>nope</body></html>", status=403, content_type="text/html"
    )
    url = httpserver.url_for("/forbidden")

    fetcher = CurlCffiPageFetcher()
    results = await fetcher.fetch_pages([url])

    assert results[url].fall_back is True


async def test_curl_cffi_marks_fallback_on_bot_wall(httpserver: HTTPServer) -> None:
    """A 200 that matches the bot-wall regex flags the result for fallback."""
    httpserver.expect_request("/wall").respond_with_data(
        _CLOUDFLARE_INTERSTITIAL, content_type="text/html"
    )
    url = httpserver.url_for("/wall")

    fetcher = CurlCffiPageFetcher()
    results = await fetcher.fetch_pages([url])

    assert results[url].fall_back is True


async def test_curl_cffi_marks_fallback_on_network_error() -> None:
    """A connection refused error is captured and flagged for fallback."""
    url = "http://127.0.0.1:1/never-listens"

    fetcher = CurlCffiPageFetcher()
    results = await fetcher.fetch_pages([url])

    assert results[url].fall_back is True
    assert results[url].text == ""


async def test_curl_cffi_caps_text_at_content_limit(httpserver: HTTPServer) -> None:
    """Curl tier honors the same character cap as the Playwright tier."""
    from odin.fetch import CONTENT_LIMIT  # noqa: PLC0415 — local to keep test self-contained

    big = "<html><body><article><p>" + ("x" * 50_000) + "</p></article></body></html>"
    httpserver.expect_request("/big").respond_with_data(big, content_type="text/html")
    url = httpserver.url_for("/big")

    fetcher = CurlCffiPageFetcher()
    results = await fetcher.fetch_pages([url])

    assert len(results[url].text) <= CONTENT_LIMIT

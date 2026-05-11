"""Tests for the curl_cffi tier of the fetch pipeline.

These tests cover the pure ``should_fall_back`` predicate plus the
``CurlCffiPageFetcher`` against an in-process ``pytest-httpserver`` fixture.
Both pieces live in ``odin.curl_fetch``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

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


@pytest.mark.parametrize(
    ("status_code", "html", "extracted", "expected"),
    [
        pytest.param(200, _LONG_ARTICLE, _CLEAN_EXTRACTION, False, id="clean-article"),
        pytest.param(403, _LONG_ARTICLE, _CLEAN_EXTRACTION, True, id="4xx-status"),
        pytest.param(502, _LONG_ARTICLE, _CLEAN_EXTRACTION, True, id="5xx-status"),
        pytest.param(200, _CLOUDFLARE_INTERSTITIAL, "short", True, id="cloudflare-interstitial"),
        pytest.param(200, _ACCESS_DENIED, "short", True, id="access-denied"),
        pytest.param(200, _ATTENTION_REQUIRED, "short", True, id="attention-required"),
        pytest.param(200, _HEAVY_HTML_NO_ARTICLE, "x" * 50, True, id="low-extraction-ratio"),
        pytest.param(
            200, "<html><body><p>ok</p></body></html>", "ok", False, id="genuinely-tiny-page"
        ),
    ],
)
def test_should_fall_back(status_code: int, html: str, extracted: str, *, expected: bool) -> None:
    """Each fallback signal — status, bot-wall regex, low extraction ratio — fires correctly."""
    assert should_fall_back(status_code, html, extracted) is expected


async def test_curl_cffi_happy_path(httpserver: HTTPServer) -> None:
    """A well-formed HTML article is fetched and extracted, with no fallback flag."""
    httpserver.expect_request("/article").respond_with_data(_LONG_ARTICLE, content_type="text/html")
    url = httpserver.url_for("/article")

    fetcher = CurlCffiPageFetcher()
    results = await fetcher.fetch_pages([url])

    assert url in results
    assert results[url].fall_back is False
    assert "quick brown fox" in results[url].text


@pytest.mark.parametrize(
    ("path", "body", "status"),
    [
        pytest.param("/forbidden", "<html><body>nope</body></html>", 403, id="403-response"),
        pytest.param("/wall", _CLOUDFLARE_INTERSTITIAL, 200, id="cloudflare-interstitial-200"),
    ],
)
async def test_curl_cffi_marks_fallback(
    httpserver: HTTPServer, path: str, body: str, status: int
) -> None:
    """Responses that match the predicate get flagged for Playwright fallback."""
    httpserver.expect_request(path).respond_with_data(body, status=status, content_type="text/html")
    url = httpserver.url_for(path)

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

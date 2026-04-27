"""Tests for the fetch module.

These tests run a real headless Chromium against an in-process pytest-httpserver
fixture. The browser fixture is per-test (function scoped) for simplicity; if
suite runtime grows, switch to a session-scoped browser via
``pytest_asyncio.fixture(loop_scope="session")``.
"""

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from playwright.async_api import Browser, async_playwright
from pytest_httpserver import HTTPServer
from werkzeug.wrappers import Request as WerkzeugRequest
from werkzeug.wrappers import Response as WerkzeugResponse

from odin import fetch
from odin.fetch import CONTENT_LIMIT, PlaywrightPageFetcher

_LONG_BODY = (
    "<html><body><article><h1>Title</h1><p>"
    "This page has plenty of text content so trafilatura will recognize it as "
    "a real article and return a non-empty extraction. Repeated filler keeps "
    "the body above trafilatura's minimum length: "
    + ("the quick brown fox jumps over the lazy dog. " * 30)
    + "</p></article></body></html>"
)


@pytest_asyncio.fixture
async def browser() -> AsyncIterator[Browser]:
    """Launch and tear down a fresh headless Chromium per test."""
    async with async_playwright() as playwright:
        instance = await playwright.chromium.launch(headless=True)
        try:
            yield instance
        finally:
            await instance.close()


async def test_fetch_pages_returns_content_for_each_url(
    browser: Browser, httpserver: HTTPServer
) -> None:
    """PlaywrightPageFetcher returns a dict entry with non-empty content for each URL."""
    httpserver.expect_request("/a").respond_with_data(_LONG_BODY, content_type="text/html")
    httpserver.expect_request("/b").respond_with_data(_LONG_BODY, content_type="text/html")

    urls = [httpserver.url_for("/a"), httpserver.url_for("/b")]
    result = await PlaywrightPageFetcher(browser).fetch_pages(urls)

    assert set(result.keys()) == set(urls)
    assert all(len(v) > 0 for v in result.values())


async def test_fetch_pages_caps_content_at_limit(browser: Browser, httpserver: HTTPServer) -> None:
    """fetch_pages returns at most CONTENT_LIMIT characters per URL."""
    big = "<html><body><article><p>" + ("x" * 50_000) + "</p></article></body></html>"
    httpserver.expect_request("/big").respond_with_data(big, content_type="text/html")

    urls = [httpserver.url_for("/big")]
    result = await PlaywrightPageFetcher(browser).fetch_pages(urls)

    assert len(result[urls[0]]) <= CONTENT_LIMIT


async def test_fetch_pages_captures_error_without_failing_batch(
    browser: Browser, httpserver: HTTPServer
) -> None:
    """A single bad URL does not fail the batch; its slot contains an error string."""
    httpserver.expect_request("/ok").respond_with_data(_LONG_BODY, content_type="text/html")

    urls = [httpserver.url_for("/ok"), "http://127.0.0.1:1/never-listens"]
    result = await PlaywrightPageFetcher(browser).fetch_pages(urls)

    assert len(result[urls[0]]) > 0
    assert "Error" in result[urls[1]]


async def test_fetch_pages_extracts_js_rendered_content(
    browser: Browser, httpserver: HTTPServer
) -> None:
    """Content injected by JavaScript is captured after Playwright renders the page."""
    page_html = """
    <html><body>
      <div id="placeholder"></div>
      <script>
        document.getElementById('placeholder').innerHTML =
          '<article><h1>JS Title</h1><p>This paragraph was rendered by '
          + 'JavaScript and should be visible to Playwright but never to a '
          + 'static HTTP fetcher. The body needs enough text to satisfy '
          + 'trafilatura: lorem ipsum dolor sit amet consectetur adipiscing '
          + 'elit, sed do eiusmod tempor incididunt ut labore et dolore '
          + 'magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation '
          + 'ullamco laboris nisi ut aliquip ex ea commodo consequat.</p>'
          + '</article>';
      </script>
    </body></html>
    """
    httpserver.expect_request("/js").respond_with_data(page_html, content_type="text/html")

    urls = [httpserver.url_for("/js")]
    result = await PlaywrightPageFetcher(browser).fetch_pages(urls)

    assert "rendered by" in result[urls[0]]


async def test_fetch_pages_blocks_heavy_resources(browser: Browser, httpserver: HTTPServer) -> None:
    """Image, media, font, and stylesheet requests are aborted before reaching the server."""
    image_hits: list[int] = []

    def image_handler(_request: WerkzeugRequest) -> WerkzeugResponse:
        image_hits.append(1)
        return WerkzeugResponse(b"\x89PNG\r\n", content_type="image/png")

    page_html = (
        '<html><body><img src="/img.png" alt=""><article><p>'
        + ("the body has plenty of words for the test to be interesting. " * 10)
        + "</p></article></body></html>"
    )
    httpserver.expect_request("/page").respond_with_data(page_html, content_type="text/html")
    httpserver.expect_request("/img.png").respond_with_handler(image_handler)

    await PlaywrightPageFetcher(browser).fetch_pages([httpserver.url_for("/page")])

    assert image_hits == [], "image request should have been aborted by the route handler"


async def test_fetch_pages_handles_navigation_timeout(
    browser: Browser,
    httpserver: HTTPServer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A page that fails to load within the timeout returns an error string."""
    monkeypatch.setattr(fetch, "GOTO_TIMEOUT_MS", 200)

    def slow_handler(_request: WerkzeugRequest) -> WerkzeugResponse:
        import time as _time  # noqa: PLC0415 — keep stdlib import local to the slow handler

        _time.sleep(2)
        return WerkzeugResponse(_LONG_BODY, content_type="text/html")

    httpserver.expect_request("/slow").respond_with_handler(slow_handler)

    urls = [httpserver.url_for("/slow")]
    result = await PlaywrightPageFetcher(browser).fetch_pages(urls)

    assert "Error" in result[urls[0]]

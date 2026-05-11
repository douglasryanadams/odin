"""Tests for ``odin.fetch`` — the hardened Playwright tier plus shared helpers.

These tests run a real headless Chromium against an in-process pytest-httpserver
fixture. The browser is bundled Chromium (no ``channel="chrome"``) so the suite
does not require Google Chrome to be installed on the test host; production
launches with ``channel="chrome"`` from ``main.py:lifespan`` instead.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest_asyncio
from playwright.async_api import async_playwright
from werkzeug.wrappers import Response as WerkzeugResponse

from odin import fetch
from odin.fetch import (
    CONTENT_LIMIT,
    VIEWPORT_ANCHORS,
    PlaywrightPageFetcher,
    choose_viewport,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

    import pytest
    from playwright.async_api import Browser
    from pytest_httpserver import HTTPServer
    from werkzeug.wrappers import Request as WerkzeugRequest

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
    result = await PlaywrightPageFetcher(browser=browser).fetch_pages(urls)

    assert set(result.keys()) == set(urls)
    assert all(len(v) > 0 for v in result.values())


async def test_fetch_pages_caps_content_at_limit(browser: Browser, httpserver: HTTPServer) -> None:
    """fetch_pages returns at most CONTENT_LIMIT characters per URL."""
    big = "<html><body><article><p>" + ("x" * 50_000) + "</p></article></body></html>"
    httpserver.expect_request("/big").respond_with_data(big, content_type="text/html")

    urls = [httpserver.url_for("/big")]
    result = await PlaywrightPageFetcher(browser=browser).fetch_pages(urls)

    assert len(result[urls[0]]) <= CONTENT_LIMIT


async def test_fetch_pages_captures_error_without_failing_batch(
    browser: Browser, httpserver: HTTPServer
) -> None:
    """A single bad URL does not fail the batch; its slot contains an error string."""
    httpserver.expect_request("/ok").respond_with_data(_LONG_BODY, content_type="text/html")

    urls = [httpserver.url_for("/ok"), "http://127.0.0.1:1/never-listens"]
    result = await PlaywrightPageFetcher(browser=browser).fetch_pages(urls)

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
    result = await PlaywrightPageFetcher(browser=browser).fetch_pages(urls)

    assert "rendered by" in result[urls[0]]


async def test_fetch_pages_does_not_block_stylesheets_images_or_fonts(
    browser: Browser, httpserver: HTTPServer
) -> None:
    """Stylesheet, image, and font requests reach the origin — no route-handler blocking."""
    css_hits: list[int] = []
    img_hits: list[int] = []

    def css_handler(_request: WerkzeugRequest) -> WerkzeugResponse:
        css_hits.append(1)
        return WerkzeugResponse(b"body { color: red; }", content_type="text/css")

    def img_handler(_request: WerkzeugRequest) -> WerkzeugResponse:
        img_hits.append(1)
        return WerkzeugResponse(b"\x89PNG\r\n", content_type="image/png")

    page_html = (
        '<html><head><link rel="stylesheet" href="/style.css"></head>'
        '<body><img src="/img.png" alt=""><article><p>'
        + ("the body has plenty of words for the test to be interesting. " * 10)
        + "</p></article></body></html>"
    )
    httpserver.expect_request("/page").respond_with_data(page_html, content_type="text/html")
    httpserver.expect_request("/style.css").respond_with_handler(css_handler)
    httpserver.expect_request("/img.png").respond_with_handler(img_handler)

    await PlaywrightPageFetcher(browser=browser).fetch_pages([httpserver.url_for("/page")])

    assert css_hits, "stylesheet should be loaded (resource blocking removed)"
    assert img_hits, "image should be loaded (resource blocking removed)"


async def test_fetch_pages_handles_navigation_timeout(
    browser: Browser,
    httpserver: HTTPServer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A page that never loads within the timeout returns an error string after retry."""
    monkeypatch.setattr(fetch, "GOTO_TIMEOUT_MS", 200)

    def slow_handler(_request: WerkzeugRequest) -> WerkzeugResponse:
        import time as _time  # noqa: PLC0415 — keep stdlib import local to the slow handler

        _time.sleep(2)
        return WerkzeugResponse(_LONG_BODY, content_type="text/html")

    httpserver.expect_request("/slow").respond_with_handler(slow_handler)

    urls = [httpserver.url_for("/slow")]
    result = await PlaywrightPageFetcher(browser=browser).fetch_pages(urls)

    assert "Error" in result[urls[0]]


async def test_fetch_pages_retries_with_load_wait_on_first_failure(
    browser: Browser,
    httpserver: HTTPServer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the first ``domcontentloaded`` attempt errors, retry once with ``load``.

    Simulated via a handler that fails the first request and succeeds the
    second; assert we got real content rather than the first-attempt error.
    """
    monkeypatch.setattr(fetch, "GOTO_TIMEOUT_MS", 1_500)

    call_count = {"n": 0}

    def flaky_handler(_request: WerkzeugRequest) -> WerkzeugResponse:
        call_count["n"] += 1
        if call_count["n"] == 1:
            return WerkzeugResponse(b"", status=503)
        return WerkzeugResponse(_LONG_BODY, content_type="text/html")

    httpserver.expect_request("/flaky").respond_with_handler(flaky_handler)

    urls = [httpserver.url_for("/flaky")]
    result = await PlaywrightPageFetcher(browser=browser).fetch_pages(urls)

    assert call_count["n"] >= 2, "retry should have occurred"
    assert "quick brown fox" in result[urls[0]]


def test_choose_viewport_returns_anchor_with_jitter() -> None:
    """Every random pick is one of the published anchors ±20px on each axis."""
    anchors = set(VIEWPORT_ANCHORS)
    for _ in range(200):
        viewport = choose_viewport()
        nearest = min(
            anchors,
            key=lambda a: abs(viewport["width"] - a[0]) + abs(viewport["height"] - a[1]),
        )
        assert abs(viewport["width"] - nearest[0]) <= 20
        assert abs(viewport["height"] - nearest[1]) <= 20


def test_viewport_anchors_match_planned_set() -> None:
    """Guard against accidental edits to the anchor list."""
    assert set(VIEWPORT_ANCHORS) == {(1366, 768), (1536, 864), (1440, 900)}


async def test_fetch_pages_applies_locale_and_timezone(
    browser: Browser, httpserver: HTTPServer
) -> None:
    """``navigator.language`` and ``Intl`` timezone reflect the configured locale."""
    page_html = (
        """
    <html><body>
      <article id="out"><p>
      Placeholder body text long enough for trafilatura to keep the article.
      """
        + ("Filler sentence to satisfy the extractor. " * 20)
        + """
      </p></article>
      <script>
        document.querySelector('#out p').textContent =
          'lang=' + navigator.language + ' tz=' +
          Intl.DateTimeFormat().resolvedOptions().timeZone;
      </script>
    </body></html>
    """
    )
    httpserver.expect_request("/locale").respond_with_data(page_html, content_type="text/html")

    urls = [httpserver.url_for("/locale")]
    result = await PlaywrightPageFetcher(browser=browser).fetch_pages(urls)

    assert "lang=en-US" in result[urls[0]]
    assert "tz=America/Los_Angeles" in result[urls[0]]


async def test_fetch_pages_sends_accept_language_header(
    browser: Browser, httpserver: HTTPServer
) -> None:
    """Outbound requests carry ``Accept-Language: en-US,en;q=0.9``."""
    seen_headers: dict[str, str] = {}

    def header_handler(request: WerkzeugRequest) -> WerkzeugResponse:
        seen_headers["accept_language"] = request.headers.get("Accept-Language", "")
        return WerkzeugResponse(_LONG_BODY, content_type="text/html")

    httpserver.expect_request("/hdr").respond_with_handler(header_handler)

    await PlaywrightPageFetcher(browser=browser).fetch_pages([httpserver.url_for("/hdr")])

    assert "en-US" in seen_headers["accept_language"]


async def test_storage_state_round_trip(
    browser: Browser, httpserver: HTTPServer, tmp_path: Path
) -> None:
    """A cookie set on the first batch is present on the second batch via storage_state."""
    state_path = tmp_path / "state.json"
    sent_cookies: list[str] = []

    def set_cookie_handler(_request: WerkzeugRequest) -> WerkzeugResponse:
        resp = WerkzeugResponse(_LONG_BODY, content_type="text/html")
        resp.set_cookie("session", "abc123", path="/")
        return resp

    def echo_cookie_handler(request: WerkzeugRequest) -> WerkzeugResponse:
        sent_cookies.append(request.cookies.get("session", ""))
        return WerkzeugResponse(_LONG_BODY, content_type="text/html")

    httpserver.expect_request("/set").respond_with_handler(set_cookie_handler)
    httpserver.expect_request("/echo").respond_with_handler(echo_cookie_handler)

    fetcher1 = PlaywrightPageFetcher(browser=browser, storage_state_path=str(state_path))
    await fetcher1.fetch_pages([httpserver.url_for("/set")])

    assert state_path.exists(), "storage_state should be persisted after the batch"

    fetcher2 = PlaywrightPageFetcher(browser=browser, storage_state_path=str(state_path))
    await fetcher2.fetch_pages([httpserver.url_for("/echo")])

    assert sent_cookies == ["abc123"]


async def test_storage_state_persist_skipped_when_lock_unavailable(
    browser: Browser,
    httpserver: HTTPServer,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the lock can't be acquired, persist is skipped and the fetch still succeeds.

    Stubs out :func:`fetch._acquire_lock` so the test doesn't wait on real
    locking — the contract under test is "fail gracefully," not "wait N seconds."
    """
    state_path = tmp_path / "state.json"

    async def _never_acquires(_fd: int, _deadline: float) -> bool:
        return False

    monkeypatch.setattr(fetch, "_acquire_lock", _never_acquires)

    httpserver.expect_request("/q").respond_with_data(_LONG_BODY, content_type="text/html")
    fetcher = PlaywrightPageFetcher(browser=browser, storage_state_path=str(state_path))
    result = await fetcher.fetch_pages([httpserver.url_for("/q")])

    assert len(result[httpserver.url_for("/q")]) > 0
    assert not state_path.exists(), "persist should have been skipped on lock timeout"


async def test_storage_state_recovers_from_corrupt_file(
    browser: Browser, httpserver: HTTPServer, tmp_path: Path
) -> None:
    """Garbage in state.json doesn't crash the launch — we fall back to empty state."""
    state_path = tmp_path / "state.json"
    state_path.write_text("this is not valid json {{{ }}}")

    httpserver.expect_request("/recover").respond_with_data(_LONG_BODY, content_type="text/html")

    fetcher = PlaywrightPageFetcher(browser=browser, storage_state_path=str(state_path))
    result = await fetcher.fetch_pages([httpserver.url_for("/recover")])

    assert len(result[httpserver.url_for("/recover")]) > 0
    rewritten = json.loads(state_path.read_text())
    assert "cookies" in rewritten

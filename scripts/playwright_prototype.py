"""Compare httpx + trafilatura against three Playwright extraction strategies.

Run inside the dev container (headless):

    docker-compose run --rm web uv run python scripts/playwright_prototype.py \
        https://example.com https://en.wikipedia.org/wiki/Pluto

Run on the host (headed; watch the browser):

    uv run playwright install chromium
    uv run python scripts/playwright_prototype.py --headed https://example.com

Optional --trace writes a Playwright trace .zip; view it with
``uvx playwright show-trace <path>``.
"""

from __future__ import annotations

import argparse
import asyncio
import time
from dataclasses import dataclass
from typing import cast

import httpx
import trafilatura
from playwright.async_api import (
    BrowserContext,
    Page,
    Request,
    Route,
    ViewportSize,
    async_playwright,
)

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)
VIEWPORT: ViewportSize = {"width": 1280, "height": 800}
GOTO_TIMEOUT_MS = 15_000
HTTPX_TIMEOUT_S = 10.0
HEAVY_RESOURCES = frozenset({"image", "media", "font", "stylesheet"})
PREVIEW_CHARS = 200
ERROR_PREVIEW_CHARS = 80
READABILITY_JS_URL = "https://unpkg.com/@mozilla/readability@0.5.0/Readability.js"
READABILITY_EVAL = (
    "() => { const a = new Readability(document.cloneNode(true)).parse(); "
    "return a ? a.textContent : ''; }"
)
METHODS = (
    "httpx+trafilatura",
    "pw+content+trafilatura",
    "pw+inner_text",
    "pw+readability",
)


@dataclass(frozen=True)
class Sample:
    """One extraction attempt: which method, how big, how long, did it work."""

    url: str
    method: str
    chars: int
    elapsed_ms: float
    error: str | None
    preview: str


async def _block_heavy(route: Route, request: Request) -> None:
    if request.resource_type in HEAVY_RESOURCES:
        await route.abort()
    else:
        await route.continue_()


async def baseline_httpx(url: str) -> Sample:
    """Fetch via httpx and extract with trafilatura — today's production path."""
    start = time.perf_counter()
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, follow_redirects=True, timeout=HTTPX_TIMEOUT_S)
            response.raise_for_status()
            extracted = trafilatura.extract(response.text)
            text = extracted or response.text
    except Exception as exc:
        return _error_sample(url, "httpx+trafilatura", start, exc)
    return _ok_sample(url, "httpx+trafilatura", start, text)


async def pw_content_trafilatura(page: Page, url: str) -> Sample:
    """Render via Playwright, then run trafilatura on the rendered HTML."""
    start = time.perf_counter()
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=GOTO_TIMEOUT_MS)
        html = await page.content()
        extracted = trafilatura.extract(html)
        text = extracted or html
    except Exception as exc:
        return _error_sample(url, "pw+content+trafilatura", start, exc)
    return _ok_sample(url, "pw+content+trafilatura", start, text)


async def pw_inner_text(page: Page, url: str) -> Sample:
    """Render via Playwright and return ``body.innerText`` directly."""
    start = time.perf_counter()
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=GOTO_TIMEOUT_MS)
        text = await page.inner_text("body")
    except Exception as exc:
        return _error_sample(url, "pw+inner_text", start, exc)
    return _ok_sample(url, "pw+inner_text", start, text)


async def pw_readability(page: Page, url: str) -> Sample:
    """Render via Playwright, then extract using injected Mozilla Readability.js."""
    start = time.perf_counter()
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=GOTO_TIMEOUT_MS)
        await page.add_script_tag(url=READABILITY_JS_URL)
        text = cast("str", await page.evaluate(READABILITY_EVAL))
    except Exception as exc:
        return _error_sample(url, "pw+readability", start, exc)
    return _ok_sample(url, "pw+readability", start, text)


def _ok_sample(url: str, method: str, start: float, text: str) -> Sample:
    elapsed = (time.perf_counter() - start) * 1000
    return Sample(
        url=url,
        method=method,
        chars=len(text),
        elapsed_ms=elapsed,
        error=None,
        preview=text[:PREVIEW_CHARS],
    )


def _error_sample(url: str, method: str, start: float, exc: BaseException) -> Sample:
    elapsed = (time.perf_counter() - start) * 1000
    return Sample(
        url=url,
        method=method,
        chars=0,
        elapsed_ms=elapsed,
        error=str(exc),
        preview="",
    )


async def _sample_url_via_playwright(context: BrowserContext, url: str) -> list[Sample]:
    page = await context.new_page()
    try:
        return [
            await pw_content_trafilatura(page, url),
            await pw_inner_text(page, url),
            await pw_readability(page, url),
        ]
    finally:
        await page.close()


async def run(urls: list[str], *, headless: bool, trace_path: str | None) -> None:
    """Run all four strategies against each URL, then print a comparison table."""
    samples: list[Sample] = [await baseline_httpx(url) for url in urls]

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=headless)
        context = await browser.new_context(user_agent=USER_AGENT, viewport=VIEWPORT)
        await context.route("**/*", _block_heavy)
        if trace_path:
            await context.tracing.start(screenshots=True, snapshots=True, sources=True)
        try:
            for url in urls:
                samples.extend(await _sample_url_via_playwright(context, url))
        finally:
            if trace_path:
                await context.tracing.stop(path=trace_path)
            await context.close()
            await browser.close()

    print_table(samples, urls)


def print_table(samples: list[Sample], urls: list[str]) -> None:
    """Print a per-URL table comparing all four extraction methods."""
    by_url: dict[str, dict[str, Sample]] = {url: {} for url in urls}
    for sample in samples:
        by_url[sample.url][sample.method] = sample

    for url in urls:
        print(f"\n=== {url} ===")
        print(f"{'method':<26} {'chars':>8} {'ms':>10}  status")
        for method in METHODS:
            sample = by_url[url].get(method)
            if sample is None:
                continue
            status = (
                f"ERR: {sample.error[:ERROR_PREVIEW_CHARS]}" if sample.error is not None else "ok"
            )
            print(f"{method:<26} {sample.chars:>8} {sample.elapsed_ms:>10.0f}  {status}")


def main() -> None:
    """Parse argv and run the comparison harness."""
    parser = argparse.ArgumentParser(
        description="Compare httpx+trafilatura vs Playwright extraction strategies.",
    )
    _ = parser.add_argument("urls", nargs="+", help="URLs to compare")
    _ = parser.add_argument(
        "--headed",
        action="store_true",
        help="Run with a visible browser window (host only; no display in Docker)",
    )
    _ = parser.add_argument("--trace", help="Path to write a Playwright trace .zip")
    args = parser.parse_args()
    urls = cast("list[str]", args.urls)
    headed = cast("bool", args.headed)
    trace = cast("str | None", args.trace)
    asyncio.run(run(urls, headless=not headed, trace_path=trace))


if __name__ == "__main__":
    main()

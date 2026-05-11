# Backend

Python lives under `src/odin/` as one flat package — no subpackages. Front-end assets sit alongside under `templates/` and `static/` and are documented in [`frontend.md`](./frontend.md).

## Module map

| File | Responsibility |
|---|---|
| `main.py` | FastAPI app, routes, dependency providers, static + template wiring. |
| `pipeline.py` | Orchestrates the profile build as an async generator. |
| `claude.py` | Anthropic API calls — one function per stage. |
| `searxng.py` | Async SearXNG client; defines `SearchResult`. |
| `fetch.py` | Tiered page fetch: hardened Playwright (Tier 1) plus orchestration via `TieredPageFetcher`. Defines the `PageFetcher` Protocol and `PlaywrightPageFetcher`. |
| `curl_fetch.py` | Tier 0 fetcher: `curl_cffi` with Chrome TLS impersonation. Defines `CurlCffiPageFetcher`, `CurlFetchResult`, and the `_should_fall_back` predicate. |
| `models.py` | `Profile`, `ProfileHighlight`, `TimelineEntry`, `Citation`, `Assessment`, the `Category` literal. |
| `log.py` | `loguru` setup, stdlib bridging, `/health` access-log filter. |

## FastAPI app

`main.py` calls `log.setup()` at import, instantiates `app = FastAPI(lifespan=lifespan)`, mounts `/static`, configures Jinja2 templates. The `lifespan` async-context-manager launches one hardened Chromium per worker on startup (headless unless `PLAYWRIGHT_HEADLESS=false`, with `--disable-blink-features=AutomationControlled` and `--disable-features=IsolateOrigins,site-per-process`) and stores it on `app.state.browser`; it closes on shutdown. `PLAYWRIGHT_CHANNEL` can swap in a system-installed browser channel when one is available; we'll revisit a `chrome` channel default once Google ships a native arm64 Chrome build. An ungraceful kill (`SIGKILL`) leaves the Chromium subprocess to be reaped by the OS.

| Route | Handler | Notes |
|---|---|---|
| `GET /` | `index()` | Renders `index.html`. |
| `GET /health` | `health()` | Returns `{"status": "ok"}`. |
| `GET /profile?q=` | `profile_page()` | Renders `profile.html`. |
| `GET /profile/stream?q=` | `profile_stream()` | SSE endpoint that drives the pipeline. |

Three dependency providers, used with `Annotated[..., Depends(...)]` and overridden in tests:

- `get_searxng_url()` — reads `SEARXNG_URL` (default `http://searxng:8080`).
- `get_anthropic_client()` — returns `AsyncAnthropic()`, which itself reads `ANTHROPIC_API_KEY`.
- `get_page_fetcher(request)` — returns `TieredPageFetcher(curl=CurlCffiPageFetcher(), playwright=PlaywrightPageFetcher(browser=...))` so each batch tries Tier 0 first.

## Profile pipeline

`pipeline.build_profile(query, searxng_url, anthropic_client, fetcher)` is an async generator yielding a `StageEvent(stage, data)` per step:

1. **`categorized`** — `claude.categorize()` → `person | place | event | other` (Haiku).
2. **`queries`** — `claude.generate_queries()` → 3–5 search strings (Haiku).
3. **`searching`** — Run queries against SearXNG, gated by `asyncio.Semaphore(SEARXNG_MAX_CONCURRENCY=2)`. Dedupe by URL, preserving first-seen order.
4. **`fetching`** — `claude.select_urls()` picks ≤ 5 URLs (Haiku); the event carries the count.
5. **`profile`** — `fetcher.fetch_pages()` runs each URL through Tier 0 (`curl_cffi` with `impersonate="chrome"`, 8 s timeout, `trafilatura.extract`); any URL whose result has `fall_back=True` is then rendered in a fresh Playwright `BrowserContext` with locale `en-US`, timezone `America/Los_Angeles`, an `Accept-Language` header, a randomized viewport drawn from `(1366, 768)`, `(1536, 864)`, or `(1440, 900)` ±20 px, an init script that hides `navigator.webdriver`, and an optional shared `storage_state` JSON file persisted under an `fcntl` lock. The first `domcontentloaded` attempt is retried once with `wait_until="load"` if the extraction is too short. Each result is capped at `CONTENT_LIMIT = 10_000` chars. `claude.synthesize()` then builds the `Profile` (Sonnet); yielded as `Profile.model_dump()`. Page-level errors are mapped to `"Error fetching URL: <exc>"` so a single bad URL does not fail the batch.
6. **`assessment`** — `claude.assess()` scores the profile + sources on confidence, sentiment, subject/source political bias, D&D law-chaos / good-evil, and a short caveats list (Sonnet). If the call raises, the stage is skipped and a warning is logged so the profile still reaches the user.

`profile_stream` emits a terminal `{"type": "done"}` SSE event after the generator is exhausted.

## SSE streaming

The streaming layer lives entirely inside `profile_stream()` in `main.py`:

```python
async def event_generator() -> AsyncGenerator[str, None]:
    async for event in pipeline.build_profile(q, searxng_url, anthropic, fetcher):
        payload = {"type": event.stage, **event.data}
        yield f"data: {json.dumps(payload)}\n\n"
    yield 'data: {"type": "done"}\n\n'

return StreamingResponse(event_generator(), media_type="text/event-stream")
```

Each event is one JSON object on a single SSE `data:` line. The browser consumes it with `EventSource` ([`profile.js`](../src/odin/static/js/profile.js)).

## Integrations

- **SearXNG** — `searxng.search()` is one async function, ~30 lines. Concurrency and dedup live in `pipeline.py`. See [`searxng.md`](./searxng.md).
- **Anthropic** — Five async functions in `claude.py`, each using tool-use to enforce structured output. Haiku for classify/queries/select-urls; Sonnet for synthesis and assessment. See [`claude-api.md`](./claude-api.md).

## Logging

`log.setup()` configures `loguru`, level from `LOG_LEVEL` (default `INFO`). `_odin_only_at_debug` drops sub-WARNING records from non-`odin` modules. `_InterceptHandler` routes stdlib `logging` into loguru. `HealthCheckFilter` is attached to `uvicorn.access` so healthchecks don't flood the log.

## Tests

`tests/` mirrors the module layout: `test_main.py`, `test_pipeline.py`, `test_claude.py`, `test_fetch.py`, `test_log.py`, plus `tests/integration/` (marked `integration`, requires a live SearXNG, off by default). Run modes are in the [Makefile](../Makefile) and explained in [`configuration.md`](./configuration.md).

## Design philosophy

- **Flat package, async generators.** No subpackages; the pipeline `yield`s progress so SSE is a thin adapter on top.
- **DI for external services.** SearXNG URL and Anthropic client come in via `Depends`; tests swap them.
- **Tool-use, not parsing.** Structured output is enforced by tool schemas; missing tool blocks raise.

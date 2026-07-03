# Backend

Python lives under `src/odin/` as one mostly flat package; `search/` and `routes/` are the two subpackages. Front-end assets sit alongside under `templates/` and `static/` and are documented in [`frontend.md`](./frontend.md).

## Module map

| File | Responsibility |
| --- | --- |
| `main.py` | Entry point gunicorn/uvicorn target (`odin.main:app`). Re-exports `app` from `odin.app` and imports `odin.routes` to register every router. |
| `app.py` | The FastAPI instance, `lifespan` (launches hardened Chromium, opens the Valkey client and Postgres pool), security-header middleware, template wiring, and the three DI providers (`get_anthropic_client`, `get_page_fetcher`, `get_valkey_client`, `get_search_aggregator`). |
| `routes/` | One router module per area, each an `APIRouter` included by `routes/__init__.py`: `pages.py` (`/`, `/health`, `/health/backends`, `/about`, `/privacy`, `/terms`, `/notice/dismiss`), `profile.py` (`/profile`, `/profile/stream`), `auth.py` (`/login`, `/auth/*`), `account.py` (`/dashboard`, `/account/delete`). `_shared.py` holds cross-router helpers (`anon_cookie_id`, `csrf_token_value`, the CSRF/bot-defense form). |
| `pipeline.py` | Orchestrates the profile build as an async generator: `build_profile` (fast) and `build_deep_profile` (bounded agentic mode — initial pass, gap analysis, follow-up rounds, connection pass). |
| `claude.py` | Anthropic API calls — one function per stage, including the deep-mode additions `identify_gaps` and `find_connections`. |
| `search/` | The search layer. `models.py` defines the neutral `SearchResult`; `base.py` the `SearchBackend` Protocol; `aggregator.py` the `SearchAggregator` (fan-out, per-backend timeout, dedupe by URL with engines-union) plus the shared `merge_results` helper; `brave.py` and `wikipedia.py` are first-party clients for the Brave Search API and the Wikimedia Core REST search endpoint; `metrics.py` records per-backend outcomes to Valkey. `__init__.py` holds the backend registry (`_brave_factory`, `_wikipedia_factory`) and `build_aggregator(settings, recorder)`. See [`search.md`](./search.md). |
| `fetch.py` | Tiered page fetch: hardened Playwright (Tier 1) plus orchestration via `TieredPageFetcher`. Defines the `PageFetcher` Protocol and `PlaywrightPageFetcher`. |
| `curl_fetch.py` | Tier 0 fetcher: `curl_cffi` with Chrome TLS impersonation. Defines `CurlCffiPageFetcher`, `CurlFetchResult`, the `_should_fall_back` predicate, and the response-shape gates (`ALLOWED_CONTENT_TYPES`, `MAX_RESPONSE_BYTES`). |
| `url_filter.py` | Pure allowlist for URLs sent to Claude. Rejects non-`http(s)` schemes, known-binary extensions, and hosts in the configured domain blocklist. Applied by `pipeline.py` before `select_urls`. |
| `models.py` | `Profile` (with `locations`), `ProfileHighlight`, `TimelineEntry`, `Citation`, `Location`, `Connection`, `Caveat`, `Assessment`, the `Category` and `ConnectionKind` literals. |
| `cache.py` | 24-hour Valkey cache of the raw SSE event list per (normalized query, mode), plus a canonical-name alias pointer so spelling variants share one cached result. |
| `log.py` | `loguru` setup, stdlib bridging, `/health` access-log filter. |

## FastAPI app

`app.py` calls `log.setup()` at import, instantiates `app = FastAPI(lifespan=lifespan)`, and configures Jinja2 templates. Static assets (`/static/*`, `/favicon.ico`, `/robots.txt`) are not served by Python — the Nginx sidecar handles them directly. The `lifespan` async-context-manager launches one hardened Chromium per worker on startup (headless unless `PLAYWRIGHT_HEADLESS=false`, with `--disable-blink-features=AutomationControlled` and `--disable-features=IsolateOrigins,site-per-process`), connects the shared Valkey client, and opens the Postgres pool — all three stored on `app.state` and closed on shutdown. `PLAYWRIGHT_CHANNEL` can swap in a system-installed browser channel when one is available; we'll revisit a `chrome` channel default once Google ships a native arm64 Chrome build. An ungraceful kill (`SIGKILL`) leaves the Chromium subprocess to be reaped by the OS.

| Route | Handler | Router | Notes |
| --- | --- | --- | --- |
| `GET /` | `index()` | `pages` | Renders `index.html`. |
| `GET /health` | `health()` | `pages` | Returns `{"status": "ok"}`. |
| `GET /health/backends` | `health_backends()` | `pages` | Per-backend search health, from `search/metrics.py`. |
| `GET /about` | `about()` | `pages` | Static about page. |
| `GET /profile?q=&deep=` | `profile_page()` | `profile` | Renders `profile.html`; `deep=true` opts into the agentic mode. |
| `GET /profile/stream?q=&deep=` | `profile_stream()` | `profile` | SSE endpoint that drives the pipeline (cache lookup, then fast or deep pipeline). |
| `GET /privacy`, `GET /terms` | `privacy()`, `terms()` | `pages` | Static policy pages; render the `CONTACT_EMAIL` setting. |
| `POST /notice/dismiss` | `dismiss_notice()` | `pages` | CSRF-protected; sets a cookie that hides the beta/privacy banner. |
| `GET /login` | `login_page()` | `auth` | Magic-link sign-in form. |
| `POST /auth/send-link` | `send_link()` | `auth` | Issues and emails (or logs) a one-time login token. |
| `GET /auth/verify` | `auth_verify()` | `auth` | Consumes a token and starts a session. |
| `POST /auth/logout` | `logout()` | `auth` | Clears the session cookie. |
| `GET /dashboard` | `dashboard()` | `account` | Signed-in user dashboard (quota, account controls). |
| `POST /account/delete` | `account_delete()` | `account` | Deletes the signed-in user's account. |

Dependency providers live in `app.py`, used with `Annotated[..., Depends(...)]` and overridden in tests:

- `get_search_aggregator(valkey_client)` — returns `search.build_aggregator(settings, search_metrics.make_recorder(valkey_client))`, a `SearchAggregator` over the active backends (Brave when `BRAVE_API_KEY` is set, Wikipedia always) that also records per-backend outcomes to Valkey.
- `get_anthropic_client()` — returns `AsyncAnthropic(max_retries=0)`; the SDK's retry is disabled so `claude._create_with_retries` is the single source of truth for attempts and backoff.
- `get_page_fetcher(request)` — returns `TieredPageFetcher(curl=CurlCffiPageFetcher(), playwright=PlaywrightPageFetcher(browser=...))` so each batch tries Tier 0 first.
- `get_valkey_client(request)` — returns the shared client opened in `lifespan`.

## Profile pipeline

`pipeline.build_profile(query, searcher, anthropic_client, fetcher)` is the fast-profile async generator, yielding a `StageEvent(stage, data)` per step (`searcher` is any `SearchBackend`; in production the `SearchAggregator`):

1. **`categorized`** — `claude.categorize()` → `person | place | event | other` (Haiku).
2. **`queries`** — `claude.generate_queries()` → 3–5 search strings (Haiku).
3. **`searching`** — Run each query through `searcher.search()`, gated by `asyncio.Semaphore(SEARCH_QUERY_CONCURRENCY=2)`. The aggregator fans each query across its enabled backends concurrently under a per-backend timeout, dropping any that time out or error (partial results allowed). Results are merged by `merge_results()`: deduped by URL preserving first-seen order, with the `engines` field unioned across backends that returned the same URL — the same helper collapses results across queries. Then apply `url_filter.filter_search_results()` against `settings.url_domain_blocklist` to drop results with non-`http(s)` schemes, known-binary extensions, or hosts in the blocklist. Only the filtered set is forwarded to `select_urls` and used as the citation-candidate pool for `synthesize`.
4. **`fetching`** — `claude.select_urls()` picks ≤ 5 URLs (Haiku); the event carries the count.
5. **`synthesizing` → `profile`** — `fetcher.fetch_pages()` runs each URL through Tier 0 (`curl_cffi` with `impersonate="chrome"`, 8 s timeout, `trafilatura.extract`). The Tier 0 response is gated by `ALLOWED_CONTENT_TYPES` (`text/html`, `text/plain`, `application/xhtml+xml`) and `MAX_RESPONSE_BYTES` (2 MB); a response that fails either check is discarded with `fall_back=False` so Playwright is not retried. Otherwise, any URL whose result has `fall_back=True` is rendered in a fresh Playwright `BrowserContext` with locale `en-US`, timezone `America/Los_Angeles`, an `Accept-Language` header, a randomized viewport drawn from `(1366, 768)`, `(1536, 864)`, or `(1440, 900)` ±20 px, an init script that hides `navigator.webdriver`, and an optional shared `storage_state` JSON file persisted under an `fcntl` lock. The first `domcontentloaded` attempt is retried once with `wait_until="load"` if the extraction is too short. Each result is capped at `CONTENT_LIMIT = 10_000` chars. If every fetched page comes back blank, the pipeline yields `service_unavailable` and refuses to synthesize rather than let Claude invent a profile with no grounding. Otherwise `claude.synthesize_and_assess()` builds the `Profile` and the `Assessment` in one Sonnet call; `profile` is yielded first.
6. **`assessment`** — the same call's audit half: sentiment, subject/source political bias, D&D law-chaos / good-evil, and a short caveats list. If the call returned no assessment, the stage is skipped and a warning is logged so the profile still reaches the user.

`build_deep_profile(query, searcher, anthropic_client, fetcher)` is the opt-in agentic mode (`_run_deep_pipeline`): it runs the same initial categorize → queries → search → fetch sequence, but synthesizes a **draft** (never yielded as a `profile` event) and hands it to `claude.identify_gaps()`, which returns up to `DEEP_MODE_MAX_ROUNDS` (2) `(query, reason)` pairs. `_run_followup_rounds` runs one bounded round per gap — search, dedupe against already-fetched content, `select_urls`, fetch — skipping silently (no event, no extra Claude call) when a round finds nothing new. `_run_connection_pass` then runs once, over the full merged set, via `claude.find_connections()`; every returned `Connection` has already been resolved to at least two distinct cited sources (`_resolve_connection_citations`) — the grounding guarantee the product depends on. Both modes converge on the same `_finish_pipeline` (steps 5–6 above), so a `profile` event looks identical either way; the deep-only difference is richer `content`/`sources` and the extra `deep_gap_analysis` / `deep_searching` / `deep_fetching` / `deep_connecting` / `connections` events along the way.

Both pipelines route through `_run_with_degraded_errors`: an Anthropic rate limit or billing cap yields a `service_unavailable` event instead of a stack trace, since it means Odin itself is temporarily out of capacity, not that the query failed.

## SSE streaming and caching

The streaming layer lives in `profile_stream()` in `routes/profile.py`. Before running any pipeline it checks the Valkey cache (`cache.py`) in three fast paths — exact/normalized query match, a canonical-name alias pointer (0 Claude calls), and an early `categorize()` call that checks the canonical cache under the resolved name — so repeat and near-duplicate queries skip the pipeline entirely. On a cache miss it runs `build_deep_profile` or `build_profile` depending on the `deep` flag:

```python
async def event_generator() -> AsyncGenerator[str, None]:
    ...
    async for event in pipeline_events:
        payload = {"type": event.stage, **event.data}
        collected.append(payload)
        yield f"data: {json.dumps(payload)}\n\n"
    yield 'data: {"type": "done"}\n\n'
    if not _had_failure(collected):
        await cache.put(valkey_client, canonical_for_cache, mode, collected)
```

Each event is one JSON object on a single SSE `data:` line; the browser consumes it with `EventSource` ([`profile.js`](../static/js/profile.js)). What `cache.py` stores is the **raw list of SSE event dicts**, not a rendered `Profile` — a cache hit replays the same frames (`_replay_cached`) rather than serving pre-rendered HTML or JSON. There is currently no way to fetch a finished profile outside this SSE replay.

## Integrations

- **Search** — Queries fan out through the `SearchAggregator` over registered `SearchBackend`s. Today: `BraveBackend` (when `BRAVE_API_KEY` is set) and `WikipediaBackend` (always). Per-query concurrency lives in `pipeline.py`; per-backend timeout and the dedupe/engines-union merge live in `search/aggregator.py`. See [`search.md`](./search.md).
- **Anthropic** — Async functions in `claude.py`, each using tool-use to enforce structured output. Haiku for categorize/generate-queries/select-urls; Sonnet for `synthesize_and_assess` (one call for both the fast profile and its assessment), plus the deep-mode-only `identify_gaps` and `find_connections`. See [`claude-api.md`](./claude-api.md).

## Persistence

Two datastores, split by the nature of the data. ValKey holds the ephemeral, TTL-evicted state: rate-limit counters and magic-link nonces (`store.py`) and the 24-hour profile cache (`cache.py`). PostgreSQL holds the durable, queryable data: anonymized signups (`signups.py`) and search history (`history.py`). Postgres runs in-stack as the `odin-postgres` compose service in both dev and prod; lifting it to a managed instance later is a `DATABASE_URL` change.

- **`db.py`** — opens the `asyncpg` pool in the lifespan and exposes the `get_db_pool` dependency (sibling to `get_valkey_client`). Runtime queries are hand-written SQL; SQLAlchemy enters only through Alembic at migration time.
- **`identity.py`** — `hash_email` (the truncated SHA-256 that keys a user in both stores, so no raw email is stored) and the frozen `Requester` value object (`user_email`, `cookie_id`, `ip_address`) that rate limiting and history take instead of three loose arguments.
- **`signups.py`** — a row per email recorded on magic-link verify (`record_signup` upserts; reporting helpers count signups), removed on account deletion.
- **`history.py`** — one row per search; anonymous rows carry both cookie id and IP and are read with an `OR`, so clearing one identifier still surfaces history. Signed-in history is removed on account deletion; anonymous history is retained indefinitely for abuse prevention (no automatic sweep).
- **`alembic/`** — hand-written migrations; see [`configuration.md`](./configuration.md) (Database & migrations).

Account deletion (`account_delete`) spans both stores: `store.delete_user` clears the ValKey counters, `signups.delete_signup` and `history.delete_user_history` remove the user's Postgres rows.

## Logging

`log.setup()` configures `loguru`, level from `LOG_LEVEL` (default `INFO`). `_odin_only_at_debug` drops sub-WARNING records from non-`odin` modules. `_InterceptHandler` routes stdlib `logging` into loguru. `HealthCheckFilter` is attached to `uvicorn.access` so healthchecks don't flood the log.

## Tests

`tests/` mirrors the module layout, one file per router or module (`test_pages.py`, `test_profile.py`, `test_auth.py`/`test_auth_routes.py`, `test_account.py`, `test_pipeline.py`, `test_claude.py`, `test_cache.py`, `test_store.py`, `test_fetch.py`/`test_tiered_fetch.py`/`test_curl_fetch.py`, the `search/` suite, etc.), plus `tests/integration/` (marked `integration`, hits real external services, off by default). Run modes are in the [Makefile](../Makefile) and explained in [`configuration.md`](./configuration.md).

## Design philosophy

- **Mostly flat package, async generators.** `routes/` and `search/` are the only subpackages; the pipeline `yield`s progress so SSE is a thin adapter on top.
- **DI for external services.** The search aggregator and Anthropic client come in via `Depends`; tests swap them (a fake `SearchBackend`, an aggregator over a mock URL).
- **Tool-use, not parsing.** Structured output is enforced by tool schemas; missing tool blocks raise.

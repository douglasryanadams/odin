# Search

Odin's search layer is first-party: backends call upstream APIs directly through `httpx`, return a neutral `SearchResult`, and the pipeline fans queries across every active backend in parallel.

## Layout

The whole search layer lives under `src/odin/search/`:

| File | Role |
| --- | --- |
| `models.py` | `SearchResult` (`url`, `title`, `content`, `engines: list[str]`). Every backend returns a list of these. |
| `base.py` | `SearchBackend` Protocol (`name`, `timeout_seconds`, `async search(query)`). Backends raise on upstream failure; the aggregator owns the decision to degrade. |
| `aggregator.py` | `SearchAggregator` and the `merge_results` helper. Runs each backend concurrently under its own timeout, swallows per-backend timeouts and exceptions (partial results allowed), and dedupes the merged set by URL while unioning the `engines` list. |
| `brave.py` | `BraveBackend` — calls `https://api.search.brave.com/res/v1/web/search` with `X-Subscription-Token`, strips Brave's highlight HTML, stamps `engines=["brave"]`. |
| `wikipedia.py` | `WikipediaBackend` — calls `https://api.wikimedia.org/core/v1/wikipedia/en/search/page` with a policy-compliant `User-Agent`, strips the `<span class="searchmatch">` excerpt markup, stamps `engines=["wikipedia"]`. Unauthenticated; no token required. |
| `__init__.py` | Backend registry (`_REGISTRY`) and `build_aggregator(settings)`. |

`build_aggregator(settings)` runs each factory in `_REGISTRY` and assembles every backend that returned non-`None`. Backends fail closed: a factory returns `None` when its required config is missing, and `app.py` calls `build_aggregator` once at startup.

## Configuration

| Env var | Default | Effect |
| --- | --- | --- |
| `BRAVE_API_KEY` | unset | When set, `_brave_factory` constructs `BraveBackend`; when missing, the factory returns `None` and Brave is skipped. Provision a key at <https://api-dashboard.search.brave.com/> (paid, ~$3–$5 per 1k queries). |
| `SEARCH_TIMEOUT_SECONDS` | `30.0` | Per-backend call ceiling enforced by the aggregator. |
| `CONTACT_EMAIL` | `odin@odinseye.info` | Composed into the Wikipedia backend's `User-Agent` for Wikimedia policy compliance. |
| `APP_URL` | — (required) | Same — used in the Wikipedia `User-Agent`. |

Wikipedia is always active (the endpoint is unauthenticated). Brave is active iff `BRAVE_API_KEY` is set.

## Adding a backend

1. Implement a class satisfying the `SearchBackend` protocol — typically a `frozen=True` dataclass with an `async def search`. Raise on upstream failure; let the aggregator degrade.
2. Add a factory `(settings) -> SearchBackend | None` to `src/odin/search/__init__.py` and register it in `_REGISTRY`.
3. Add unit tests in `tests/test_search_backends.py` using `respx` to mock the upstream API.
4. Add an integration test under `tests/integration/` that hits the real API. Mark it `@pytest.mark.integration` so it stays out of CI; gate on a secret with `pytest.skip` if one is required.

## Verifying from inside a container

With the dev stack running:

```sh
docker compose exec web python -c '
import asyncio
from odin.search.wikipedia import WikipediaBackend
results = asyncio.run(WikipediaBackend().search("Marie Curie"))
for r in results[:3]:
    print(r.url, r.title)
'
```

Same shape works for `BraveBackend(api_key=...)` if you have a key.

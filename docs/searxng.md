# SearXNG

[SearXNG](https://docs.searxng.org/) is a self-hostable meta-search engine that aggregates results from upstream engines and returns them as JSON. Odin uses it to get one consistent JSON shape across many engines, with no API key and a local-network latency tail.

## How Odin calls it

The whole client is `src/odin/searxng.py` (~30 lines). One async function:

```python
async def search(query: str, base_url: str) -> list[SearchResult]
```

It issues `GET {base_url}/search?q=<query>&format=json` (`httpx`, 30s timeout) with `X-Forwarded-For: 127.0.0.1` — SearXNG's bot detection rejects requests with no forwarded address. It returns each item in `results[]` as a `SearchResult` (`url`, `title`, `content`, `engines`).

Concurrency limiting (`asyncio.Semaphore(SEARXNG_MAX_CONCURRENCY=2)`) and dedup-by-URL live in `pipeline.py`, not here.

## Local configuration (`searxng/`)

`settings.yml`:
- **Engines:** removes `ahmia`, `torch`, `wikidata`; enables `brave`, `startpage`, `qwant`, `mojeek`.
- **Server:** `limiter: false`, `image_proxy: true`, dev `secret_key`.
- **Search formats:** `html` + `json` (Odin uses JSON).
- **Outgoing:** `request_timeout: 6`, HTTP/2, pool `100` / per-host `20`, `retries: 1`.
- **Valkey:** `redis://searxng-valkey:6379/0`.

## Verify

With the dev stack running:

```sh
curl 'http://localhost:8080/search?q=hello&format=json' \
     -H 'X-Forwarded-For: 127.0.0.1' \
     | jq '.results[0]'
```

From inside the compose network, the URL is `http://searxng:8080/...`.

## Upstream docs

- User: <https://docs.searxng.org/user/index.html>
- Admin: <https://docs.searxng.org/admin/index.html>

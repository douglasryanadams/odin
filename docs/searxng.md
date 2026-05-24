# SearXNG

[SearXNG](https://docs.searxng.org/) is a self-hostable meta-search engine that aggregates results from upstream engines and returns them as JSON. Odin uses it to get one consistent JSON shape across many engines, with no API key and a local-network latency tail.

## How Odin calls it

The whole client is `src/odin/searxng.py` (~30 lines). One async function:

```python
async def search(query: str, base_url: str) -> list[SearchResult]
```

It issues `GET {base_url}/search?q=<query>&format=json` (`httpx`, 30s timeout) with `X-Forwarded-For: 127.0.0.1` — SearXNG's bot detection rejects requests with no forwarded address. It returns each item in `results[]` as a `SearchResult` (`url`, `title`, `content`, `engines`).

Concurrency limiting (`asyncio.Semaphore(SEARXNG_MAX_CONCURRENCY=2)`) and dedup-by-URL live in `pipeline.py`, not here.

## Image pin

`compose/docker-compose.yml` pins `searxng/searxng` to a specific dated tag rather than `:latest`. Deploys auto-`--pull always`, so a moving tag would adopt upstream changes the next time main is pushed. Bump the pin in the same PR that exercises the new version.

## Local configuration (`searxng/`)

`settings.yml.tmpl` (committed; rendered to `settings.yml` at container start by `entrypoint.sh`):

- **Engines:** removes `ahmia`, `torch`, `wikidata`, `duckduckgo`, `google`, `bing`, `yahoo` from the upstream defaults; enables `braveapi` (official Brave Search API) and `mojeek` (independent index, cooperative scraper).
- **Server:** `limiter: false`, `image_proxy: true`, dev `secret_key`.
- **Search formats:** `html` + `json` (Odin uses JSON).
- **Outgoing:** `request_timeout: 6`, HTTP/2, pool `100` / per-host `20`, `retries: 1`. The commented `source_ips` block can be uncommented on hosts with reachable IPv4 + IPv6 stacks to rotate outbound requests across two source IPs.
- **Valkey:** `redis://searxng-valkey:6379/0`.

### Brave Search API key

The `braveapi` engine needs an API key. Provision one at <https://api-dashboard.search.brave.com/> (the free tier is gone as of February 2026; metered billing starts at $5 prepaid credit, ~$0.003–$0.005/query). Then expose it as `BRAVE_API_KEY` in the environment that runs `docker compose`:

- **Local dev:** add `BRAVE_API_KEY=...` to `.env` at the repo root.
- **Prod (EC2):** add `brave_api_key` to the `odin/app` Secrets Manager JSON. The deploy script's `jq` step rewrites it as `BRAVE_API_KEY=...` in `/opt/odin/.env`, and the searxng service's `environment:` passthrough in `compose/docker-compose.prod.yml` forwards it to the container. See [`aws-setup.md` § "How secrets reach the containers"](./aws-setup.md#how-secrets-reach-the-containers) for the full data flow and verification commands.

`searxng/entrypoint.sh` runs before the SearXNG image's own entrypoint, substitutes `${BRAVE_API_KEY}` into `settings.yml.tmpl`, writes the result to a **tmpfs** at `/run/searxng/settings.yml`, points SearXNG at it by exporting both `__SEARXNG_SETTINGS_PATH` (used by the upstream image entrypoint) and `SEARXNG_SETTINGS_PATH` (read by the SearXNG app itself at import time), then execs the original entrypoint. The rendered file is chmod `0400` owned by `searxng:searxng`, so the key never touches the host filesystem and is unreadable to non-root processes inside the container. If `BRAVE_API_KEY` is unset, the entrypoint exits before SearXNG can boot with an unauthenticated engine config.

### Other engines

`startpage`, `qwant`, and `karmasearch` are SearXNG defaults that we override with `disabled: true` in the engines list. They were consistently returning CAPTCHA / access-denied from our cloud IP and added latency without returning results. They cannot be dropped via `use_default_settings.engines.remove` because SearXNG's network config references some of these names as aliases (`qwant` in particular) and removal causes a `KeyError` at startup.

`mojeek` is enabled and free, but in practice it also returns `HTTP 403` from our cloud IPs. SearXNG suspends the engine for 10 min on first failure (capping at 1 hour on repeats) — see the `search.ban_time_on_fail` / `max_ban_time_on_fail` settings in `settings.yml.tmpl`. In effect `braveapi` is the only engine returning results today; a Serper backend is tracked in `TODO.md` as the next reliability step.

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

# ODIN

> _profiles synthesized from the web._

A FastAPI service that turns a search term — a person, place, event, or topic — into a structured profile (summary, highlights, lowlights, timeline). It classifies the term, plans search queries, runs them in parallel against a self-hosted [SearXNG](https://docs.searxng.org/), picks the most informative pages, and synthesizes the result with the [Anthropic API](https://platform.claude.com/docs/en/home). Progress streams to the browser as Server-Sent Events.

---

## Quick start

You'll need [Docker](https://docs.docker.com/get-docker/), `make`, and an [Anthropic API key](https://console.anthropic.com/) — the only secret required. `.env` is gitignored.

```sh
echo 'ANTHROPIC_API_KEY=sk-ant-...' > .env
make dev
```

The first `make dev` builds the Docker images and pulls SearXNG + Valkey (a few minutes). Subsequent runs reuse the cache.

Open <http://localhost:8000>, search for something — _Marie Curie_, _Reykjavik_, _the Apollo program_ — and watch each stage light up:

```
●─── Categorize ───●─── Plan queries ───●─── Search ───●─── Fetch ───●─── Synthesize
```

A first profile takes ~15–30 seconds end-to-end; SearXNG and Anthropic each do real work.

---

## Pipeline

`/profile/stream` runs an async pipeline and emits SSE progress at each stage:

1. **Categorize** the term (person / place / event / other) — Haiku
2. **Plan queries** — generate 3–5 targeted search queries — Haiku
3. **Search** SearXNG in parallel and deduplicate — capped at 2 concurrent
4. **Fetch** the best pages — URL selection by Haiku
5. **Synthesize** the structured profile — Sonnet

The browser consumes the SSE stream and renders each card progressively.

---

## Routes

| Route | Description |
|---|---|
| `GET /` | Search page; accepts `?q=`. |
| `GET /health` | Health check. |
| `GET /profile?q=` | Profile page for a query. |
| `GET /profile/stream?q=` | SSE stream of pipeline progress. |

---

## Make commands

| Command | Description |
|---|---|
| `make dev` | Start the development server with hot reload. |
| `make prod` | Start a production-like server using gunicorn. |
| `make format` | Apply ruff and djlint formatting. |
| `make lint` | Format then run the full linting suite (Python + frontend). |
| `make test` | Run unit (pytest + vitest), smoke, and integration tests with coverage. |
| `make metrics` | Print lines-of-code statistics (informational). |

All commands run inside Docker. See [`docs/configuration.md`](./docs/configuration.md) for what each linter and test target enforces.

---

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | Yes | Anthropic API key. |
| `SEARXNG_URL` | No | SearXNG base URL (default: `http://searxng:8080`). |
| `LOG_LEVEL` | No | Loguru level (default: `INFO`; compose sets `DEBUG`). |

---

## Stack

| Layer | Tools |
|---|---|
| Web | FastAPI · gunicorn (prod) · uvicorn (dev) · loguru |
| Front-end | Vanilla CSS + JS · Jinja2 · EventSource — Orbitron / Inter / JetBrains Mono |
| Search | SearXNG · Valkey |
| Models | Anthropic Claude — Haiku 4.5 · Sonnet 4.6 |
| Container | Multi-stage Dockerfile · docker-compose (Node sidecar for JS/CSS tooling) |
| Python QA | ruff · pyright · xenon · bandit · detect-secrets · djlint · pytest |
| JS / CSS QA | eslint · stylelint · vitest (happy-dom) |

---

## Contributor docs

For "where do I find what" in the codebase, start at [`docs/README.md`](./docs/README.md). Coding standards live in [`docs/coding-standards.md`](./docs/coding-standards.md).

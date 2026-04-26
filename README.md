# Odin

A Python web service built with FastAPI, managed with [uv](https://docs.astral.sh/uv/), and containerised with Docker.

The service exposes a search interface backed by [SearXNG](https://docs.searxng.org/) and an AI-powered profile feature that turns a search term into a structured profile (summary, highlights, lowlights, timeline) using the Anthropic API.

## Prerequisites

- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- [Docker](https://docs.docker.com/get-docker/) and docker-compose
- An [Anthropic API key](https://console.anthropic.com/) (required for the profile feature)

## Make commands

| Command | Description |
|---|---|
| `make dev` | Build and start the development server with hot reload |
| `make prod` | Build and start a production-like server using gunicorn |
| `make format` | Apply ruff formatting to the codebase |
| `make lint` | Format then run the full linting suite (see below) |
| `make test` | Run the test suite with coverage and timing reports |
| `make metrics` | Print lines-of-code statistics (informational, never fails) |

All commands run inside Docker via docker-compose for consistency.

## Project setup

### Runtime

| Tool | Role |
|---|---|
| FastAPI | Web framework |
| Gunicorn + UvicornWorker | Production ASGI server (`gunicorn.conf.py`) |
| Uvicorn | Development ASGI server (with `--reload`) |
| SearXNG | Privacy-respecting meta-search engine (runs as a sidecar service) |
| Valkey | In-memory cache used by SearXNG |
| Anthropic API | AI-powered profile generation (Haiku for classification/queries, Sonnet for synthesis) |
| loguru | Structured, colour-coded application logging |

### Docker images

Two images are built from a single multi-stage `Dockerfile`:

- **`odin-prod`** (`docker-compose.prod.yml`) — production image; installs runtime dependencies only and serves via gunicorn.
- **`odin-dev`** (`docker-compose.yml`) — extends `odin-prod`; adds dev dependencies and serves via uvicorn with hot reload. Source is bind-mounted at `/app` so changes take effect without rebuilding.

The virtual environment lives at `/opt/venv` (set via `UV_PROJECT_ENVIRONMENT`) so it is never shadowed by the source bind mount.

Both stacks bring up SearXNG and Valkey as sidecar services. `ANTHROPIC_API_KEY` is passed through from the host environment to the app container.

### Environment variables

| Variable | Required | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | Yes (profile feature) | Anthropic API key |
| `SEARXNG_URL` | No | SearXNG base URL (default: `http://searxng:8080`) |

### Application routes

| Route | Description |
|---|---|
| `GET /` | Search page; accepts `?q=` query parameter |
| `GET /health` | Health check; returns `{"status": "ok"}` |
| `GET /profile` | Profile page; accepts `?q=` query parameter |
| `GET /profile/stream` | SSE endpoint that streams pipeline progress for a profile |

### Profile pipeline

The `/profile/stream` endpoint runs a multi-step async pipeline and streams progress via Server-Sent Events:

1. Categorise the term (person / place / event / other) — Haiku
2. Generate 3–5 targeted search queries — Haiku
3. Run parallel SearXNG searches and deduplicate results
4. Select the best URLs — Haiku
5. Fetch pages and synthesise a structured profile (summary, highlights, lowlights, timeline) — Sonnet

The profile page connects via `EventSource` and progressively renders each stage; DOM manipulation uses `textContent`/`createElement` to avoid XSS from AI-generated content.

### Linting

`make lint` runs the following tools in order:

| Tool | What it enforces |
|---|---|
| `ruff format` | Consistent code formatting |
| `ruff check` | All rules enabled (`select = ["ALL"]`); McCabe complexity ≤ 8 |
| `pyright` | Strict static type checking |
| `xenon` | Cyclomatic complexity: absolute ≤ B, module average ≤ A, project average ≤ A |
| `bandit` | Security anti-patterns; fails on any low-severity/low-confidence finding |
| `detect-secrets` | Scans git-tracked files for secrets against a committed baseline |

All linting tools are configured in `pyproject.toml`. Every tool exits non-zero on a violation.

### Testing

`make test` runs pytest with:

- **Coverage** — `pytest-cov` reports per-file line coverage after every run; missing lines are shown inline.
- **Timing** — `--durations=0` shows execution time for every test.

Tests live in `tests/` and use FastAPI's `TestClient` (backed by `httpx`).

### Managing the secrets baseline

When `detect-secrets` flags a false positive, mark it as reviewed and update the baseline:

```sh
uv run detect-secrets audit .secrets.baseline
```

Commit the updated `.secrets.baseline` to record the decision.

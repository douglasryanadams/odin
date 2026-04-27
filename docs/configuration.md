# Configuration & Tooling

The repo-root [`README.md`](../README.md) summarizes Make commands and env vars. This doc is the contributor view: what each linter enforces and how the build pieces fit.

## `pyproject.toml`

- **Python:** `>= 3.12`. Built with `hatchling`.
- **Runtime deps:** `anthropic`, `fastapi`, `gunicorn`, `httpx`, `jinja2`, `loguru`, `trafilatura`, `uvicorn[standard]`.
- **Dev deps:** `bandit`, `detect-secrets`, `respx`, `pyright`, `pytest` (`-asyncio`, `-cov`), `radon`, `ruff`, `xenon`.

| Tool | Configured to enforce |
|---|---|
| `ruff format` | 100-char lines; the formatter is the source of truth for style. |
| `ruff check` | `select = ["ALL"]` (with formatter-conflict and docstring-conflict ignores). McCabe ≤ 8. `tests/**` ignores `S101` and `PLR2004`. |
| `pyright` | Python 3.12, strict mode. |
| `xenon` | Cyclomatic complexity: absolute ≤ B, per-module avg ≤ A, project avg ≤ A. |
| `bandit` | Scans `src/`. Severity and confidence both `low`. Excludes `tests/`, `.venv/`. |
| `detect-secrets` | Scans against `.secrets.baseline`. New unflagged secrets fail. |
| `pytest` | Coverage on `src/odin`. `--durations=0`. Default filter `-m 'not integration'`. `asyncio_mode = "auto"`. |

## `Makefile`

Every target runs through `docker-compose` — host needs only Docker + `make`.

| Target | Notes |
|---|---|
| `make dev` | `docker-compose up --build` (override applies; uvicorn `--reload`). |
| `make prod` | Adds `docker-compose.prod.yml`; gunicorn. |
| `make format` | `ruff format .`. |
| `make lint` | `format`, then `ruff check`, `ruff format --check`, `pyright`, `xenon`, `bandit`, `detect-secrets scan`. |
| `make metrics` | `radon raw -s .` (informational). |
| `make test` | `test-unit` → `test-smoke` → `test-integration`. |
| `make test-unit` | `pytest` with the default `not integration` filter. |
| `make test-smoke` | Builds the prod image; passes if its `/health` healthcheck reaches healthy. |
| `make test-integration` | Brings up `searxng` + `searxng-valkey`, runs `pytest -m integration`, then fails the run if service logs contain `ERROR` / `CRITICAL` (a few SearXNG-internal lines are filtered out). |

## `Dockerfile`

One multi-stage Dockerfile; two images (`odin-prod`, `odin-dev`).

- **`base`**: `python:3.12-slim` + `uv`. `UV_PROJECT_ENVIRONMENT=/opt/venv`. Venv lives at `/opt/venv` (not `/app/.venv`) so the dev compose bind-mount onto `/app` doesn't shadow it.
- **`production`** (extends `base`): copies `gunicorn.conf.py` + `src/`, `uv sync --frozen --no-dev`, `CMD gunicorn -c gunicorn.conf.py odin.main:app`.
- **`development`** (extends `production`): adds `git`, `libatomic1`; `uv sync --frozen` (with dev deps); `CMD uvicorn ... --reload`.

## Compose

- **`docker-compose.yml`** — `web` (`8000:8000`, `LOG_LEVEL=DEBUG`, `ANTHROPIC_API_KEY` passthrough, `/health` healthcheck), `searxng` (`8080:8080`, mounts `./searxng/`), `searxng-valkey` (named volume).
- **`docker-compose.override.yml`** — auto-applied. Uses `odin-dev`, builds `development`, bind-mounts `.:/app`.
- **`docker-compose.prod.yml`** — opt-in via `-f`. Uses `odin-prod`, builds `production`, `restart: always` on the SearXNG services.

## `gunicorn.conf.py`

`bind = "0.0.0.0:8000"`, `workers = (cpu_count * 2) + 1`, `worker_class = "uvicorn.workers.UvicornWorker"`, access + error logs to stdout.

## `searxng/`

- `settings.yml` — engines, dev secret key, `limiter: false`, `image_proxy: true`, JSON format, outgoing-pool tuning. Details in [`searxng.md`](./searxng.md).
- `limiter.toml` — empty stub; exists only to suppress SearXNG's missing-config warning.

## Environment variables

| Variable | Read where | Default |
|---|---|---|
| `ANTHROPIC_API_KEY` | `AsyncAnthropic()` (via the SDK) | — (required) |
| `SEARXNG_URL` | `get_searxng_url()` in `main.py` | `http://searxng:8080` |
| `LOG_LEVEL` | `setup()` in `log.py` | `INFO` (compose sets `DEBUG`) |

`.env` is gitignored and is the conventional place for `ANTHROPIC_API_KEY`.

## Secrets baseline

`detect-secrets` runs on every `make lint` against `.secrets.baseline`. Accept a new finding with:

```sh
uv run detect-secrets audit .secrets.baseline
```

Commit the updated baseline.

## CI

There is no CI workflow yet. Quality gates are `make lint` and `make test`, run locally. Adding CI means lifting Make targets into a workflow file — it shouldn't change what gets enforced.

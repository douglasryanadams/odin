# Configuration & Tooling

The repo-root [`README.md`](../README.md) summarizes Make commands and env vars. This doc is the contributor view: what each linter enforces and how the build pieces fit.

## `pyproject.toml`

- **Python:** `>= 3.12`. Built with `hatchling`.
- **Runtime deps:** `anthropic`, `fastapi`, `gunicorn`, `httpx`, `jinja2`, `loguru`, `playwright`, `trafilatura`, `uvicorn[standard]`.
- **Dev deps:** `bandit`, `detect-secrets`, `djlint`, `respx`, `pyright`, `pytest` (`-asyncio`, `-cov`, `-httpserver`), `radon`, `ruff`, `xenon`.

| Tool | Configured to enforce |
|---|---|
| `ruff format` | 100-char lines; the formatter is the source of truth for style. |
| `ruff check` | `select = ["ALL"]` (with formatter-conflict and docstring-conflict ignores). McCabe ≤ 8. `tests/**` ignores `S101` and `PLR2004`. |
| `pyright` | Python 3.12, strict mode. |
| `xenon` | Cyclomatic complexity: absolute ≤ B, per-module avg ≤ A, project avg ≤ A. |
| `bandit` | Scans `src/`. Severity and confidence both `low`. Excludes `tests/`, `.venv/`. |
| `detect-secrets` | Scans against `.secrets.baseline`. New unflagged secrets fail. |
| `djlint` | Jinja profile, 2-space indent, 100-char lines. Lints + reformats `src/odin/templates/`. |
| `pytest` | Coverage on `src/odin`. `--durations=0`. Default filter `-m 'not integration'`. `asyncio_mode = "auto"`. |

## Frontend tooling (Node sidecar)

Eslint, stylelint, and vitest run inside a `node:20-slim` container that lives in the `tools` Docker Compose profile, so the default `make dev` never starts it. `package.json` and `package-lock.json` are committed for reproducible `npm ci` installs; the `node_modules` Make target is a sentinel that re-runs `npm ci` only when `package.json` / `package-lock.json` change.

| File | Purpose |
|---|---|
| `package.json` | Pins eslint, stylelint, stylelint-config-standard, vitest, happy-dom, globals. |
| `package-lock.json` | Locked install graph for `npm ci`. |
| `eslint.config.js` | Flat config. Targets `src/odin/static/js/**/*.js` as `script` source type with browser globals + `ODIN_QUERY` readonly; `no-undef` error, `no-unused-vars` warn. |
| `.stylelintrc.json` | Extends `stylelint-config-standard`. BEM-friendly `selector-class-pattern` (`block`, `block__element`, `block--modifier`). Disables a handful of opinionated rules (color/alpha notation, vendor prefixes, media-feature range, shorthand reductions, value keyword case) to match existing CSS. |
| `vitest.config.js` | `happy-dom` environment; collects `tests/js/**/*.test.js`. |
| `tests/js/loadProfile.js` | Test harness that reads `profile.js` and runs it inside a `node:vm` context whose globals come from happy-dom — lets the script-global file expose helpers to tests without an `export` keyword. |

## `Makefile`

Every target runs through `docker-compose` — host needs only Docker + `make`.

| Target | Notes |
|---|---|
| `make dev` | `docker-compose up --build` (override applies; uvicorn `--reload`). |
| `make prod` | Adds `docker-compose.prod.yml`; gunicorn. |
| `make format` | `ruff format .` plus `djlint --reformat` on the templates. |
| `make lint` | `format`, `lint-frontend`, then `ruff check`, `ruff format --check`, `pyright`, `xenon`, `bandit`, `detect-secrets scan`. |
| `make lint-frontend` | Depends on `node_modules`. Runs `djlint --check` on templates, `stylelint` on CSS, and `eslint` on JS. |
| `make node_modules` | Sentinel target; runs `npm ci` in the `node` sidecar when `package.json` / `package-lock.json` change. |
| `make metrics` | `radon raw -s .` (informational). |
| `make test` | `test-unit` → `test-smoke` → `test-integration`. |
| `make test-unit` | `pytest` (with the default `not integration` filter), then `make test-js`. |
| `make test-js` | `npx vitest run` in the `node` sidecar; covers `profile.js` helpers. |
| `make test-smoke` | Builds the prod image; passes if its `/health` healthcheck reaches healthy. |
| `make test-integration` | Brings up `searxng` + `searxng-valkey`, runs `pytest -m integration`, then fails the run if service logs contain `ERROR` / `CRITICAL` (a few SearXNG-internal lines are filtered out). |

## `Dockerfile`

One multi-stage Dockerfile; two images (`odin-prod`, `odin-dev`).

- **`base`**: `python:3.12-slim` + `uv`. `UV_PROJECT_ENVIRONMENT=/opt/venv`. Venv lives at `/opt/venv` (not `/app/.venv`) so the dev compose bind-mount onto `/app` doesn't shadow it.
- **`production`** (extends `base`): copies `gunicorn.conf.py` + `src/`, `uv sync --frozen --no-dev`, then `playwright install --with-deps chromium` (~300 MB; brings the prod image to ~600 MB), `CMD gunicorn -c gunicorn.conf.py odin.main:app`.
- **`development`** (extends `production`): adds `git`, `libatomic1`; `uv sync --frozen` (with dev deps); `CMD uvicorn ... --reload`. Chromium and its system libraries are inherited from the production stage.

## Compose

- **`docker-compose.yml`** — `web` (`8000:8000`, `LOG_LEVEL=DEBUG`, `ANTHROPIC_API_KEY` passthrough, `/health` healthcheck), `searxng` (`8080:8080`, mounts `./searxng/`), `searxng-valkey` (named volume), `node` (`node:20-slim`, mounts `.:/workspace`, gated by the `tools` profile so it stays out of `make dev`).
- **`docker-compose.override.yml`** — auto-applied. Uses `odin-dev`, builds `development`, bind-mounts `.:/app`.
- **`docker-compose.prod.yml`** — opt-in via `-f`. Uses `odin-prod`, builds `production`, `restart: always` on the SearXNG services.

## `gunicorn.conf.py`

`bind = "0.0.0.0:8000"`, `workers = WORKERS env || (cpu_count * 2) + 1`, `worker_class = "uvicorn.workers.UvicornWorker"`, access + error logs to stdout. Each worker holds its own Chromium (~200 MB resident) launched in the FastAPI lifespan, so on small boxes set `WORKERS` explicitly — rule of thumb: 1 worker per ~350 MB of headroom.

## `searxng/`

- `settings.yml` — engines, dev secret key, `limiter: false`, `image_proxy: true`, JSON format, outgoing-pool tuning. Details in [`searxng.md`](./searxng.md).

## Environment variables

| Variable | Read where | Default |
|---|---|---|
| `ANTHROPIC_API_KEY` | `AsyncAnthropic()` (via the SDK) | — (required) |
| `SEARXNG_URL` | `get_searxng_url()` in `main.py` | `http://searxng:8080` |
| `LOG_LEVEL` | `setup()` in `log.py` | `INFO` (compose sets `DEBUG`) |
| `PLAYWRIGHT_HEADLESS` | `lifespan()` in `main.py` | `true` (set `false` to launch a visible Chromium — only useful on a host with a display server) |
| `PLAYWRIGHT_TRACE_DIR` | `_fetch_pages_playwright()` in `fetch.py` | unset (when set, each `fetch_pages` call writes a `.zip` trace; view with `uvx playwright show-trace`) |
| `WORKERS` | `gunicorn.conf.py` | `(cpu_count * 2) + 1` |
| `SEARXNG_SECRET` | `searxng/settings.yml` via SearXNG env | unset (required in production — overrides `secret_key`) |
| `SMTP_HOST` | `Settings` in `config.py`, used by `email.py` | `smtp.purelymail.com` |
| `SMTP_FROM` | `Settings` in `config.py`, used by `email.py` | `odin@odinseye.info` |
| `SMTP_USER` | `Settings` in `config.py`, used by `email.py` | unset (required in production — without it, magic links are not sent and a `WARNING` is logged) |
| `SMTP_PASS` | `Settings` in `config.py`, used by `email.py` | unset (required when `SMTP_USER` is set) |
| `SMTP_TEST_RECIPIENT` | `tests/integration/test_email_smtp.py` | unset (required for the SMTP integration test; set to your own address so devs don't share an inbox) |

`.env` is gitignored and is the conventional place for secrets. `.env.example` documents all variables. `traces/` is gitignored for `PLAYWRIGHT_TRACE_DIR` output.

In production these must be set as host environment variables before `make prod`; `docker-compose.prod.yml` forwards them into the container. The `.env` file is not mounted in production (only the dev override mounts it).

## Secrets baseline

`detect-secrets` runs on every `make lint` against `.secrets.baseline`. Accept a new finding with:

```sh
uv run detect-secrets audit .secrets.baseline
```

Commit the updated baseline.

## CI/CD

GitHub Actions workflows live in `.github/workflows/`:

| File | Trigger | What it does |
|---|---|---|
| `ci.yml` | Pull request → `main` | Builds dev image, runs `make lint` + `make test-unit test-smoke` |
| `deploy.yml` | Push → `main` | Builds prod image, pushes to ECR, deploys to EC2 via SSM |

The deploy workflow uses OIDC — no long-lived AWS credentials stored in GitHub. Required repository secrets: `AWS_ACCOUNT_ID`, `EC2_INSTANCE_ID`. See [`docs/aws-setup.md`](./aws-setup.md) for full provisioning steps.

Integration tests are excluded from CI — they require a live SearXNG instance hitting real search engines. Run them locally with `make test-integration`.

# Configuration & Tooling

The repo-root [`README.md`](../README.md) is the orientation page. This doc is the operator manual: every env var, every Make target, every linter, every build piece.

## `pyproject.toml`

- **Python:** `>= 3.12`. Built with `hatchling`.
- **Runtime deps:** `anthropic`, `fastapi`, `gunicorn`, `httpx`, `jinja2`, `loguru`, `playwright`, `trafilatura`, `uvicorn[standard]`.
- **Dev deps:** `bandit`, `djlint`, `respx`, `pyright`, `pytest` (`-asyncio`, `-cov`, `-httpserver`), `radon`, `ruff`, `xenon`, `textstat` (Markdown readability scoring; see `make readability`).

| Tool | Configured to enforce |
|---|---|
| `ruff format` | 100-char lines; the formatter is the source of truth for style. |
| `ruff check` | `select = ["ALL"]` (with formatter-conflict and docstring-conflict ignores). McCabe ≤ 8. `tests/**` ignores `S101` and `PLR2004`. |
| `pyright` | Python 3.12, strict mode. |
| `xenon` | Cyclomatic complexity: absolute ≤ B, per-module avg ≤ A, project avg ≤ A. |
| `bandit` | Scans `src/`. Severity and confidence both `low`. Excludes `tests/`, `.venv/`. |
| `djlint` | Jinja profile, 2-space indent, 100-char lines. Lints + reformats `src/odin/templates/`. |
| `pytest` | Coverage on `src/odin`. `--durations=0`. Default filter `-m 'not integration'`. `asyncio_mode = "auto"`. |

## Frontend & docs tooling (Node sidecar)

Eslint, stylelint, vitest, markdownlint-cli2, and markdown-link-check all run inside a `node:20-slim` container that lives in the `tools` Docker Compose profile, so the default `make dev` never starts it. `package.json` and `package-lock.json` are committed for reproducible `npm ci` installs; the `node_modules` Make target is a sentinel that re-runs `npm ci` only when `package.json` / `package-lock.json` change.

| File | Purpose |
|---|---|
| `package.json` | Pins eslint, stylelint, stylelint-config-standard, vitest, happy-dom, globals, markdownlint-cli2, markdown-link-check. |
| `package-lock.json` | Locked install graph for `npm ci`. |
| `config/eslint.config.js` | Flat config. Targets `static/js/**/*.js` as `script` source type with browser globals + `ODIN_QUERY` readonly; `no-undef` error, `no-unused-vars` warn. |
| `config/.stylelintrc.json` | Extends `stylelint-config-standard`. BEM-friendly `selector-class-pattern` (`block`, `block__element`, `block--modifier`). Disables a handful of opinionated rules (color/alpha notation, vendor prefixes, media-feature range, shorthand reductions, value keyword case) to match existing CSS. |
| `config/vitest.config.js` | `happy-dom` environment; collects `tests/js/**/*.test.js`. |
| `config/.markdownlint.jsonc` | markdownlint-cli2 rules. Defaults enabled, with overrides: disable MD013 (line length), MD025 (single H1 — CLAUDE.md is flat), MD033 (inline HTML), MD036 (emphasis-as-heading); pin emphasis to `*asterisk*` and `**asterisk**` to match existing files; fenced code blocks only, backtick fences, ATX headings. |
| `config/.markdown-link-check.json` | markdown-link-check config. Validates relative file references only; `^https?://` and `^mailto:` are skipped so the lint pass stays offline and deterministic. |
| `tests/js/loadProfile.js` | Test harness that reads `profile.js` and runs it inside a `node:vm` context whose globals come from happy-dom — lets the script-global file expose helpers to tests without an `export` keyword. |

The scratch file `.notes.md` is excluded from both markdown linters.

## `Makefile`

Every target runs through `docker-compose` — host needs only Docker + `make`.

| Target | Notes |
|---|---|
| `make dev` | `docker compose -f compose/docker-compose.yml -f compose/docker-compose.override.yml up --build` (uvicorn `--reload`). |
| `make prod` | Swaps the override for `compose/docker-compose.prod.yml`; gunicorn. |
| `make format` | `ruff format .` plus `djlint --reformat` on the templates. |
| `make lint` | `format`, `lint-frontend`, `lint-markdown`, `lint-links`, then `ruff check`, `ruff format --check`, `pyright`, `xenon`, `bandit`. |
| `make lint-frontend` | Depends on `node_modules`. Runs `djlint --check` on templates, `stylelint` on CSS, and `eslint` on JS. |
| `make lint-markdown` | Depends on `node_modules`. Runs `markdownlint-cli2` over every `*.md` outside `node_modules`, `.git`, the lint caches, and `.notes.md`. |
| `make lint-links` | Depends on `node_modules`. Runs `markdown-link-check` over the same set of files. Validates relative file references only; external URLs are skipped by config so the run stays offline. |
| `make node_modules` | Sentinel target; runs `npm ci` in the `node` sidecar when `package.json` / `package-lock.json` change. |
| `make metrics` | `radon raw -s .` (informational). |
| `make readability` | `textstat` reading-level report over every `*.md` (code, tables, and frontmatter stripped). Prints Flesch-Kincaid grade and Flesch Reading Ease per file against the high-school target (grade 12, ease 50). Advisory; always exits zero. |
| `make test` | `test-unit` → `test-smoke` → `test-integration`. |
| `make test-unit` | `pytest` (with the default `not integration` filter), then `make test-js`. |
| `make test-js` | `npx vitest run` in the `node` sidecar; covers `profile.js` helpers. |
| `make test-smoke` | Brings up the full prod compose stack (`web` + `nginx` + dependencies) via `scripts/test-smoke.sh`, then asserts: `/health` proxied, `/static/css/odin.css` served by Nginx with `Cache-Control: public, max-age=86400`, `/favicon.ico` and `/robots.txt` served by Nginx, zero `GET /static/` lines in the `web` log, and `/profile/stream` responses are chunked (proves `proxy_buffering off`). Tears the stack down on exit. |
| `make test-integration` | Brings up `odin-valkey`, runs `pytest -m integration`, then fails the run if service logs contain `ERROR` / `CRITICAL`. |

## `Dockerfile`

One multi-stage Dockerfile; two images (`odin-prod`, `odin-dev`).

- **`base`**: `python:3.12-slim` + `uv`. `UV_PROJECT_ENVIRONMENT=/opt/venv`. Venv lives at `/opt/venv` (not `/app/.venv`) so the dev compose bind-mount onto `/app` doesn't shadow it.
- **`production`** (extends `base`): copies `config/gunicorn.conf.py` + `src/`, `uv sync --frozen --no-dev`, then `playwright install --with-deps chromium` (~300 MB; brings the prod image to ~600 MB), `CMD gunicorn -c gunicorn.conf.py odin.main:app`.
- **`development`** (extends `production`): adds `git`, `libatomic1`; `uv sync --frozen` (with dev deps); `CMD uvicorn ... --reload`. Chromium and its system libraries are inherited from the production stage.

## Compose

Compose files live in [`compose/`](../compose/). Every Make target invokes `docker compose --project-directory . -f compose/...` so relative paths inside the YAML (build context, `.env` discovery) keep resolving from the project root.

- **`compose/docker-compose.yml`** — `nginx` (`8000:8000`, serves `/static/*`, `/favicon.ico`, `/robots.txt` directly and proxies everything else to `web`), `web` (gunicorn on `8000` inside the network only — no host publish, `LOG_LEVEL=DEBUG`, `ANTHROPIC_API_KEY` and `BRAVE_API_KEY` passthrough, `/health` healthcheck), `odin-valkey` (named volume), `node` (`node:20-slim`, mounts `.:/workspace`, gated by the `tools` profile so it stays out of `make dev`). `nginx` mounts `./static` and `./config/nginx.conf` read-only so static-file edits are picked up live without an image rebuild.
- **`compose/docker-compose.override.yml`** — paired with the base file via `-f` for dev targets. Uses `odin-dev`, builds `development`, bind-mounts `.:/app`.
- **`compose/docker-compose.prod.yml`** — paired with the base file for prod targets. Uses `odin-prod`, builds `production`, `restart: always` on `nginx`.
- **`compose/docker-compose.awslogs.yml`** — production-only overlay applied on EC2; routes container stdout/stderr to CloudWatch log groups `/odin/web`, `/odin/nginx`, `/odin/odin-valkey`.

## `config/gunicorn.conf.py`

`bind = "0.0.0.0:8000"`, `workers = WORKERS env || (cpu_count * 2) + 1`, `worker_class = "uvicorn.workers.UvicornWorker"`, access + error logs to stdout. Each worker holds its own Chromium (~200 MB resident) launched in the FastAPI lifespan, so on small boxes set `WORKERS` explicitly — rule of thumb: 1 worker per ~350 MB of headroom.

The `web` container does not publish port 8000 to the host; Nginx is the only path in. To bypass Nginx for debugging from the host, use `docker compose exec nginx wget -O- http://web:8000/health` or attach to the compose network directly.

## `config/nginx.conf`

Single-server config mounted into the `nginx` sidecar at `/etc/nginx/conf.d/default.conf`. Listens on `8000`, serves `/static/*`, `/favicon.ico`, and `/robots.txt` directly from the bind-mounted `./static/` tree at the repo root with `Cache-Control: public, max-age=86400`, and proxies everything else to `http://web:8000`. `proxy_buffering off`, `X-Accel-Buffering: no`, and `proxy_read_timeout 130s` (just above CloudFront's 120s SSE origin timeout) keep `/profile/stream` flowing. `gzip on` is enabled for text and image/x-icon at `gzip_min_length 256`.

## Environment variables

[`config/.env.example`](../config/.env.example) is the annotated source of truth; this table groups the same variables by purpose and notes where each is read.

**Required to run.** No defaults — the app fails closed if these are missing.

| Variable | Read where | Notes |
|---|---|---|
| `ANTHROPIC_API_KEY` | `AsyncAnthropic()` via the SDK | Used by every Haiku and Sonnet call in `claude.py`. |
| `BRAVE_API_KEY` | `Settings` in `config.py` (web service's Brave backend) | Consumed directly by the web service's `BraveBackend`. Provision at <https://api-dashboard.search.brave.com/>. When unset, the Brave backend is not constructed and the aggregator falls back to Wikipedia only. In prod, store as `brave_api_key` in the `odin/app` Secrets Manager entry; see [`aws-setup.md` § "How secrets reach the containers"](./aws-setup.md#how-secrets-reach-the-containers). |
| `SECRET_KEY` | `Settings` in `config.py` | 32+ random bytes; signs session and CSRF cookies. Generate with `python -c 'import secrets; print(secrets.token_urlsafe(48))'`. |
| `APP_URL` | `Settings` in `config.py`, used by `email.py` | Public base URL of the deployment; embedded into magic-link emails. |

**Required, with safe defaults.** The example file already sets dev-appropriate values.

| Variable | Default | Notes |
|---|---|---|
| `COOKIE_SECURE` | `true` (code default; example overrides to `false`) | Production omits the override so `Secure` is set on `Set-Cookie`. Dev needs `false` because HTTP localhost cannot accept `Secure` cookies. |

**Optional runtime overrides.**

| Variable | Default | Notes |
|---|---|---|
| `LOG_LEVEL` | `INFO` (compose dev sets `DEBUG`) | Loguru level. |
| `WORKERS` | `(cpu_count * 2) + 1` | Each gunicorn worker holds ~200 MB Chromium — set explicitly on small boxes. |
| `PLAYWRIGHT_HEADLESS` | `true` | `false` launches a visible Chromium; only useful on a host with a display server. |
| `PLAYWRIGHT_TRACE_DIR` | unset | When set, each fetch writes a `.zip` trace; view with `uvx playwright show-trace`. |
| `PLAYWRIGHT_CHANNEL` | unset (bundled Chromium) | E.g. `chrome` when a real Chrome channel is installed in the image. |
| `PLAYWRIGHT_STORAGE_STATE_PATH` | `/var/lib/odin/playwright-state/state.json` | Shared cookie/storage state, persisted under an `fcntl` lock. Set `""` to disable. |
| `FETCH_CURL_CFFI_ENABLED` | `true` | Set `false` to skip Tier 0 and always use Playwright. |
| `SEARCH_TIMEOUT_SECONDS` | `30.0` | Per-backend call ceiling enforced by `SearchAggregator`. |
| `CONTACT_EMAIL` | `odin@odinseye.info` | Address shown on `/privacy` and `/terms`; also composed into the Wikipedia backend's `User-Agent`. |

**Production-only.**

| Variable | Default | Notes |
|---|---|---|
| `SMTP_HOST` | `smtp.purelymail.com` | Used by `email.py`. |
| `SMTP_PORT` | `587` | Submission port. |
| `SMTP_FROM` | `odin@odinseye.info` | `From:` header. |
| `SMTP_USER` | unset | Without it, magic links log to stdout instead of sending; a `WARNING` is logged. |
| `SMTP_PASS` | unset | Required when `SMTP_USER` is set. |

**Test-only.**

| Variable | Default | Notes |
|---|---|---|
| `SMTP_TEST_RECIPIENT` | unset | Required for `tests/integration/test_email_smtp.py`; set to your own address so devs don't share an inbox. |

`.env` is gitignored and is the conventional place for secrets in dev. `traces/` is gitignored for `PLAYWRIGHT_TRACE_DIR` output.

In production these must be set as host environment variables before `make prod`; `compose/docker-compose.prod.yml` forwards them into the container. The `.env` file is not mounted in production (only the dev override mounts it).

## Watching the browser in dev

Headless is the default, and Trace Viewer is the recommended way to see what Playwright is doing inside the dev container, since Docker has no display:

```sh
PLAYWRIGHT_TRACE_DIR=traces make dev
# trigger one /profile/stream request, then:
uvx playwright show-trace traces/<file>.zip
```

If you really want a live, visible Chromium window, run uvicorn directly on the macOS host. Note that this bypasses Nginx entirely, so `/static/*`, `/favicon.ico`, and `/robots.txt` will 404 — only use this mode for headed Playwright debugging, not full-app verification:

```sh
uv sync
uv run playwright install chromium
PLAYWRIGHT_HEADLESS=false uv run uvicorn odin.main:app --reload --port 8000
```

## CI/CD

GitHub Actions workflows live in `.github/workflows/`:

| File | Trigger | What it does |
|---|---|---|
| `ci.yml` | Pull request → `main` | Builds dev image, runs `make lint` + `make test-unit test-smoke` |
| `deploy.yml` | Push → `main` | Builds prod image, pushes to ECR, deploys to EC2 via SSM |

The deploy workflow uses OIDC — no long-lived AWS credentials stored in GitHub. Required repository secrets: `AWS_ACCOUNT_ID`, `EC2_INSTANCE_ID`. See [`docs/aws-setup.md`](./aws-setup.md) for full provisioning steps.

Integration tests are excluded from CI — they hit real external services (the Brave Search API, the Wikimedia REST endpoint, and the SMTP relay). Run them locally with `make test-integration`.

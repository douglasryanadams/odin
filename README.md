# ODIN

## Live at **[odinseye.info](https://odinseye.info)** — try it in the browser

> *profiles synthesized from the web.*

Type a name, place, event, or topic and ODIN returns a structured profile: a short summary, highlights and lowlights, a timeline, citations, and an assessment of how confident and how biased the underlying sources look. Each stage of the build streams to the page as it happens, so you watch the profile assemble in real time instead of staring at a spinner.

The hosted site is free. Anonymous visitors get 3 searches per day; signing in (magic link, no password) lifts that to 20.

This repository contains the full service: pipeline, search infrastructure, fetcher, web UI, auth, and deployment scripts.

---

## Quick start

You'll need [Docker](https://docs.docker.com/get-docker/), `make`, and three secrets:

| Key | How to get it |
|---|---|
| `ANTHROPIC_API_KEY` | Create one at <https://console.anthropic.com/>. |
| `BRAVE_API_KEY` | Create one at <https://api-dashboard.search.brave.com/>. Optional in dev: if omitted, the search aggregator falls back to Wikipedia only. |
| `SECRET_KEY` | 32+ random bytes that sign session and CSRF cookies. Generate with `python -c 'import secrets; print(secrets.token_urlsafe(48))'`. |

The example file has dev-safe defaults for everything else. Copy it, paste the secrets in, and start the stack:

```sh
cp config/.env.example .env
# edit .env: paste your ANTHROPIC_API_KEY, BRAVE_API_KEY, and a generated SECRET_KEY
make dev
```

The first `make dev` builds the Docker image and pulls Valkey (a few minutes). Subsequent runs reuse the cache. Open <http://localhost:8000>, search for something — *Marie Curie*, *Reykjavik*, *the Apollo program* — and watch each stage light up. A first profile takes ~15–30 seconds end-to-end.

---

## Where to go next

| If you want to… | Read |
|---|---|
| Understand where the product is heading and why | [`docs/vision.md`](./docs/vision.md) |
| Understand the pipeline, routes, and module layout | [`docs/backend.md`](./docs/backend.md) |
| Look up every env var, Make target, or linter setting | [`docs/configuration.md`](./docs/configuration.md) |
| Touch templates, CSS, JS, or the SSE consumer | [`docs/frontend.md`](./docs/frontend.md) |
| Add or change an Anthropic API call | [`docs/claude-api.md`](./docs/claude-api.md) |
| Understand or extend the search backends | [`docs/search.md`](./docs/search.md) |
| Work with the datastores: signups, search history, or migrations | [`docs/backend.md`](./docs/backend.md) (Persistence) and [`docs/configuration.md`](./docs/configuration.md) (Database & migrations) |

New here? Start with [`docs/backend.md`](./docs/backend.md) — the async pipeline is the heart of the project.

Coding standards are in [`docs/coding-standards.md`](./docs/coding-standards.md); prose style in [`docs/prose-style.md`](./docs/prose-style.md); design notes in [`docs/clean-code.md`](./docs/clean-code.md).

# Frontend

Three Jinja2 templates, one CSS file, one JavaScript file, no build step. Served by FastAPI directly from `src/odin/`. Style rules for JS / CSS / Jinja live in [`coding-standards.md`](./coding-standards.md); tooling configuration lives in [`configuration.md`](./configuration.md).

## Files

| Path | Purpose |
|---|---|
| `templates/_base.html` | Layout shell: head, fonts, header (`ODIN` wordmark + actions slot), `<main>`, footer, scripts slot. |
| `templates/index.html` | Landing page with the search form. |
| `templates/profile.html` | Result page: title, category badge, summary, 5-step progress strip, 6-card grid. Bootstraps `window.ODIN_QUERY`. |
| `static/css/odin.css` | Theme tokens, layout, components, animations. ~1000 lines. |
| `static/js/profile.js` | SSE consumer for `/profile/stream` and DOM renderer. No dependencies. |

## FastAPI wiring

`main.py` mounts `/static` from `src/odin/static/` and configures `Jinja2Templates` from `src/odin/templates/`. The query string is passed to `profile.html` as `query`, emitted into the page (`{{ query }}`) and the script bootstrap (`{{ query | tojson }}`).

## SSE consumer (`profile.js`)

On `DOMContentLoaded`: set the synthesis date, render stub cards (Sources, Sentiment, Mentions — gated by `STUB_DATA = true`), and if `window.ODIN_QUERY` is set, open an `EventSource` against `/profile/stream?q=...`.

Each event advances the progress strip. The `profile` event calls `renderProfile(data)` to populate the live cards. `{"type": "done"}` closes the connection. `es.onerror` flips the strip to `is-failed` and replaces the summary with a "Return to search" link.

**XSS hardening:** AI content reaches the DOM only through `textContent` and `document.createTextNode()`. The `el(tag, className, content)` helper uses `createElement` + `textContent`. There is no `innerHTML` anywhere in `profile.js`.

**State** lives in the DOM (class toggles like `is-active` / `is-done` / `is-failed`, content rebuilt via `replaceChildren()`). No virtual DOM, no router.

## Visual design — synthwave theme

Vanilla CSS with custom properties; no framework, no preprocessor.

- **Palette tokens** in `:root` of `odin.css`: dark backgrounds (`--bg`, `--surface`), magenta / cyan / violet accents.
- **Fonts** from Google Fonts: Orbitron (display), Inter (body), JetBrains Mono (timestamps).
- **Icons** from Font Awesome 6 via CDN.
- **Class naming** is BEM-ish; state classes (`is-active`, `is-done`, `is-failed`) toggle separately.
- **Layout** is a 12-column responsive card grid (`card--span-6` / `card--span-12`).

## Design philosophy

- **Vanilla over framework.** ~250 lines of JS doesn't need React. Build pipeline = "copy the file."
- **Untrusted by default.** AI output reaches the DOM only through `textContent`.
- **Progressive rendering.** Stages light up as the pipeline progresses; the page is never blank.

## Linting and tests

All four front-end gates run via `make lint` / `make test` inside Docker:

| Tool | Scope | Config |
|---|---|---|
| `djlint` | `src/odin/templates/` | `[tool.djlint]` in `pyproject.toml` (jinja profile, 2-space indent, 100-char lines). |
| `stylelint` | `src/odin/static/css/**/*.css` | `.stylelintrc.json` — `stylelint-config-standard` plus a BEM `selector-class-pattern`. |
| `eslint` | `src/odin/static/js/**/*.js` | `eslint.config.js` — flat config, browser globals, `ODIN_QUERY` readonly, `no-undef` error. |
| `vitest` | `tests/js/**/*.test.js` (happy-dom env) | `vitest.config.js`. Helpers reach the test scope via `tests/js/loadProfile.js`, which runs `profile.js` in a `node:vm` context. |

`stylelint`, `eslint`, and `vitest` run in the `node:20-slim` sidecar (compose `tools` profile). `djlint` runs in the existing `web` container alongside ruff. The `node_modules` Make target is a sentinel that re-runs `npm ci` only when `package.json` / `package-lock.json` change.

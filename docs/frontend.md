# Frontend

Jinja2 templates, a per-concern CSS module tree under `@layer`, and two JavaScript files. No build step. Templates render from `src/odin/templates/`; static assets live at the repo-root `static/` and are served by the Nginx sidecar (not Python). Style rules for JS / CSS / Jinja live in [`coding-standards.md`](./coding-standards.md); tooling configuration lives in [`configuration.md`](./configuration.md).

## Files

| Path | Purpose |
| --- | --- |
| `templates/_base.html` | Layout shell: head, fonts, header (`ODIN` wordmark + actions slot), sticky-bottom status bar (signed-in only), `<main>`, footer, scripts slot. |
| `templates/index.html` | Landing page with the search form. Hero markup carries `data-typewriter-text` on the tagline for the type-on reveal. |
| `templates/profile.html` | Result page: title, category badge, summary, single-line ASCII progress bar, 6-section main column (exposition + events + highlights + lowlights + sources) plus an anchored sidebar (Subject Compass + Source Audit). Sets `meta[name=odin-query]` for the SSE bootstrap. |
| `static/css/odin.css` | Thin entry stylesheet — declares the `@layer` order and imports the per-concern modules from `static/css/odin/`. |
| `static/css/odin/_tokens.css` | OKLCH design tokens (palette, fonts, spacing, radii). One file change re-tints the entire site. |
| `static/css/odin/_reset.css` | Box-sizing, body, button/input/anchor resets, universal phosphor halation (`text-shadow: 0 0 4px`), focus-visible bloom. |
| `static/css/odin/_typography.css` | h1/h2/h3, `.mono`, `.muted`, wordmark bloom recipe (Orbitron + doubled 1-2px solid inner halo). Defines the shared `terminal-blink` keyframe. |
| `static/css/odin/_layout.css` | Site header, footer, disclosure banner, legal page, header nav, **sticky-bottom status bar** with `$` prompt and `[KEY:value]` brackets, **bracket-framed `[ BETA ]` badge**. |
| `static/css/odin/_buttons.css` | `.btn` variants — primary uses a transparent fill + primary-colored border. `.btn--danger` re-tints from `--danger`. |
| `static/css/odin/_badges.css` | Category badge framed with `[ ... ]` pseudos; `.badge--soon` keeps an amber pill for genuine-different signal. |
| `static/css/odin/_progress.css` | ASCII pipeline bar: `[===…·===…·===…·===…·===…·===…]   N%  stage`. profile.js fills the line via `innerHTML`. |
| `static/css/odin/_gauges.css` | Single-row ASCII rules with a phosphor `▓` marker — `──·──▓──` for divergent gauges. |
| `static/css/odin/_effects.css` | Konami code-rain overlay (per-glyph alpha + hue variation) and shared `prefers-reduced-motion` guards. |
| `static/css/odin/pages/_hero.css` | Hero search box with `>` prompt prefix, `[ Return ⏎ ]` submit, hero-margin spacing, `.hero__quota.is-hidden` first-input fade. |
| `static/css/odin/pages/_profile.css` | Profile two-column layout, `>` heading prompt prefix on section h2s, bracket-framed `[FINDING-LABEL]` tags, numbered `[1] [2]` citations. Header search lives here too with the same `>` prompt. |
| `static/css/odin/pages/_auth.css` | Sign-in / confirm page. |
| `static/css/odin/pages/_dashboard.css` | Dashboard, quota bar, history list, delete-account card. |
| `static/css/odin/pages/_error.css` | Static 404 styling — Orbitron-bloom error code, fake C stacktrace. |
| `static/js/odin.js` | Site-wide: type-on for `[data-typewriter-text]`, first-input quota fade, Konami sequence → code-rain. |
| `static/js/profile.js` | SSE consumer for `/profile/stream`. Renders the ASCII progress bar (animated via `requestAnimationFrame`) and the ASCII gauges; no third-party deps. |
| `static/404.html` | Standalone 404 page served by CloudFront/nginx (not FastAPI). Mirrors `_base.html` chrome without Jinja so it works when the upstream is down. |

## FastAPI wiring

`src/odin/app.py` configures `Jinja2Templates` from `src/odin/templates/`. Static assets (`/static/*`, `/favicon.ico`, `/robots.txt`) are served by the Nginx sidecar directly from the repo-root `static/` directory — Python does not mount them. The query string is passed to `profile.html` as `query`, emitted into the page (`{{ query }}`) and the SSE bootstrap (`<meta name="odin-query" content="{{ query }}">`).

The 404 page is **not** wired into FastAPI. CloudFront `CustomErrorResponse` (or nginx `error_page 404 /404.html`) serves `static/404.html` directly so the page works even when the upstream is unhealthy.

## CSS cascade

`static/css/odin.css` declares the layer order once and imports the modules into named layers. Same-specificity rules in a later layer win; rules outside any layer beat all layered rules.

```css
@layer reset, tokens, base, components, pages;
```

- **reset** — element resets, body bloom, focus rings.
- **tokens** — `:root` design tokens; everything else consumes via `var()`.
- **base** — typography, wordmark, site chrome.
- **components** — buttons, badges, progress, gauges, effects.
- **pages** — page-specific scopes that should always beat component defaults.

Why this matters: when two rules target the same selector at equal specificity, the later layer wins. Without layers, file load order would silently decide outcomes — the kind of bug that hid in the original monolithic `odin.css` and that bit the Orbitron wordmark during the rebrand. With layers, the cascade is explicit.

## SSE consumer (`profile.js`)

On `DOMContentLoaded`: set the synthesis time (rendered as `[YYYY-MM-DDThh:mmZ]` for terminal-log feel), and if `meta[name=odin-query]` is set, open an `EventSource` against `/profile/stream?q=…`.

Each pipeline event advances the progress bar. `advanceProgress(stage)` snaps the bar to the named stage and starts an animation loop (`requestAnimationFrame`) that fills the active segment char-by-char and blinks a `▒/░` cursor at the leading edge. When the next stage event arrives, the bar snaps forward; if the current segment fills before the next event arrives, the bar holds. `completeProgress()` renders all segments filled and hides the bar; `failProgress(msg)` paints the active segment with `XXXXXXXXXX` and shows the failure message.

The `profile` event renders the title, deck, exposition, events, findings, citations; the `assessment` event (after `profile`) fills the Subject Compass (four divergent ASCII gauges) and Source Audit (one divergent gauge plus caveats). `{"type": "done"}` closes the connection. `es.onerror` flips the bar to failed and replaces the summary with a "Return to search" link.

If the backend `assess()` call fails, the stream skips the `assessment` event and ends with `done`. The Compass and Audit panels stay in their default empty state — no error UI for this secondary data.

**XSS hardening:** AI content reaches the DOM only through `textContent` and `document.createTextNode()`. The `el(tag, className, content)` helper uses `createElement` + `textContent`. The progress bar and gauges build their ASCII markup via `innerHTML`, but only from fixed template strings (`"=".repeat(n)`, `"·".repeat(n)`) plus the stage names and percent values — never from user input.

## Site-wide JS (`odin.js`)

Loaded from `_base.html` on every page (before `{% block scripts %}`):

- **Type-on** walks every `[data-typewriter-text]` element and types its content char-by-char. Status-bar values only animate on the profile page (filtered by `body.classList.contains("page-profile")`); the hero tagline animates wherever it appears. Respects `prefers-reduced-motion` (renders all text at once).
- **First-input quota fade** — when the user starts typing in the hero search box, `.hero__quota` gets `.is-hidden` (CSS opacity transition). Restores the original Odin design behavior where the explanatory line disappears once the user commits to a search.
- **Konami easter egg** — ↑↑↓↓←→←→BA outside of any text input triggers `startRain()`, which builds ~80–96 columns of half-width katakana that fall through the viewport for ~6 seconds. Each column is a stack of per-glyph spans with one of five alpha classes (`--lead` / `--bright` / `--mid` / `--dim` / `--faint`) based on position, with sparse `--blue` and `--deep` hue accents. `prefers-reduced-motion` freezes the columns mid-screen instead of animating.

`window.odin.applyTypeon` and `window.odin.startRain` are exposed for downstream pages to invoke programmatically.

## Visual design — Matrix theme

Vanilla CSS with OKLCH custom properties; no framework, no preprocessor.

- **Palette tokens** in `static/css/odin/_tokens.css`: pure CRT black with phosphor-tinted elevation, cyan-shifted phosphor green for active state, deep crimson red for danger (sparingly).
- **Fonts** from Google Fonts: Orbitron (display/wordmark, weight 900), Courier Prime (body + mono), Audiowide (fallback). Orbitron's strokes are too thin to catch a `text-shadow` bloom on their own; the wordmark recipe layers two solid 1-2px inner halos (no alpha falloff) before the larger blurs to visually thicken the strokes.
- **Icons** from Font Awesome 6 via CDN.
- **Class naming** is BEM (stylelint-enforced); state classes (`is-active`, `is-done`, `is-failed`, `is-hidden`, `is-typing`, `is-typed`) toggle separately.
- **Terminal vocabulary** runs through the design: `>` prompts on search fields and section headings, `[ ... ]` brackets on badges and submit buttons, `$` prompt on the status bar, `//` footer separators, blinking `_` cursor on the small wordmark, `[YYYY-MM-DDThh:mmZ]` synthesis timestamps.

## Design philosophy

- **Vanilla over framework.** A few hundred lines of JS doesn't need React. Build pipeline = "copy the file."
- **Untrusted by default.** AI output reaches the DOM only through `textContent` and `createTextNode`. ASCII chrome uses `innerHTML` but only from fixed template strings.
- **Progressive rendering.** Stages fill in as the pipeline progresses; the page is never blank. The progress bar's animation loop keeps the UI alive even between SSE events.
- **OKLCH-first.** All palette tokens are OKLCH so contrast steps look uniform; one token change re-tints the entire site through `color-mix()`-based variants.
- **Explicit cascade.** `@layer` orders every rule so file-load-order surprises can't happen.

## Linting and tests

All four front-end gates run via `make lint` / `make test` inside Docker:

| Tool | Scope | Config |
| --- | --- | --- |
| `djlint` | `src/odin/templates/` | `[tool.djlint]` in `pyproject.toml` (jinja profile, 2-space indent, 100-char lines). |
| `stylelint` | `static/css/**/*.css` (includes the `static/css/odin/` module tree) | `config/.stylelintrc.json` — `stylelint-config-standard` plus a BEM `selector-class-pattern`. |
| `eslint` | `static/js/**/*.js` | `config/eslint.config.js` — flat config, browser globals, `no-undef` error. |
| `vitest` | `tests/js/**/*.test.js` (happy-dom env) | `config/vitest.config.js`. Helpers reach the test scope via `tests/js/loadProfile.js`, which runs `profile.js` in a `node:vm` context with `document`, `window`, `performance`, `requestAnimationFrame` injected. |

`stylelint`, `eslint`, and `vitest` run in the `node:20-slim` sidecar (compose `tools` profile). `djlint` runs in the existing `web` container alongside ruff. The `node_modules` Make target is a sentinel that re-runs `npm ci` only when `package.json` / `package-lock.json` change.

## Regenerating favicon raster variants

The SVG (`static/favicon.svg`) is the source of truth; the PNG + ICO variants are regenerated from it. The repo has no committed pipeline for this — run the one-off Docker command when the SVG changes:

```sh
docker run --rm -v "$(pwd)/static":/static debian:bookworm-slim sh -c '
  apt-get update -qq && apt-get install -qq -y librsvg2-bin imagemagick &&
  rsvg-convert -w 32  -h 32  /static/favicon.svg -o /static/favicon-32x32.png &&
  rsvg-convert -w 180 -h 180 /static/favicon.svg -o /static/apple-touch-icon.png &&
  rsvg-convert -w 16  -h 16  /static/favicon.svg -o /tmp/16.png &&
  rsvg-convert -w 32  -h 32  /static/favicon.svg -o /tmp/32.png &&
  rsvg-convert -w 48  -h 48  /static/favicon.svg -o /tmp/48.png &&
  convert /tmp/16.png /tmp/32.png /tmp/48.png /static/favicon.ico
'
```

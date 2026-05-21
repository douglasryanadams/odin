# Matrix Rebrand

A complete visual identity change for Odin — from a Blade Runner homage (amber/navy) to a Matrix-coded phosphor terminal (green-on-black). Touches every CSS rule, every template, the favicon, the 404 page, the progress UI, the gauges, the docs.

## Goals

1. **Rebuild the palette around a single phosphor-green primary.** OKLCH tokens with hex-equivalent comments; one `--primary` value change should re-tint the entire site through `color-mix()` variants. Replace every inline `rgba(amber, X)` with `color-mix(in oklch, var(--primary) X%, transparent)`.

2. **Restate the brand vocabulary as a terminal.** Every chrome element should read as part of a session log:
   - `>` prompt prefix on search fields and section headings
   - `[ ... ]` brackets around badges (`[BETA]`, `[Historical figure]`), submit buttons (`[ Return ⏎ ]`), citation numbers (`[1]`, `[2]`), finding labels (`[ALGORITHM]`), and status-bar cells (`[KEY:value]`)
   - `$` prompt at the leading edge of the status bar
   - `//` footer separators (and inline list separators) — code-comment / URL-path feel
   - `_` blinking cursor sigil on the small wordmark — "session still attached"
   - `[YYYY-MM-DDThh:mmZ]` synthesis timestamps
   - Status bar pinned to viewport bottom as a sticky footer rather than docked under the header

3. **Make Orbitron glow on phosphor.** Earlier attempts couldn't get the wordmark bloom to register; Orbitron's strokes were too thin to anchor a `text-shadow` blur. Recipe that works:
   - `font-weight: 900` (thickest available)
   - Doubled solid inner halos at `0 0 1px var(--primary)` and `0 0 2px var(--primary)` — no alpha falloff in the inner ring; they visually thicken the strokes so the larger blurs have ink to wrap
   - Five additional blur stops at 6 / 14 / 32 / 68 / 130 px with falling chroma
   - **Specificity-safe selector**: `.wordmark.wordmark--hero` (doubled) so a same-specificity `.wordmark` rule downstream can't clobber the stack. The original cascade trap — where module load order silently decided which `text-shadow` won — is exactly the kind of thing the new `@layer` architecture also prevents.

4. **Drop placeholders, show the cursor.** The hero search input loses its placeholder text; the blinking phosphor block cursor is the only signal that it's an input. The `>` prompt sits absolute-positioned to the left of the input as the second cue.

5. **Type-on for one element per page.**
   - Hero page: only `.hero__tagline` types in (locked to *"Decrypt the public record."*)
   - Profile page: only the status-bar values type in (`PILOT: email`, `NODE: ip`)
   - Type-on filters by `body.classList.contains("page-profile")` so the status bar stays static on hero / dashboard / auth pages

6. **First-input quota fade.** Once the user starts typing in the hero search, the line below it (`X of N free searches remaining // sign in for 20/day`) fades out. Restores the original Odin design behavior where the explanatory line clears the deck once the user commits.

7. **Replace the progress strip with a single-line ASCII bar.** Six segments separated by `·`, filled char-by-char while waiting for the next SSE event, with a blinking `▒/░` cursor at the leading edge. `profile.js` drives the render via `requestAnimationFrame` so the bar feels alive even when no new data is arriving. `XXXXXXXXXX` on failure.

8. **Replace the filled-bar gauges with single-line ASCII rules.** `······▓···` for positive gauges, `──·──▓──` for divergent gauges. The phosphor `▓` marker carries the value; the rule is the track. Reads as a unix tool's output, not a UI widget.

9. **Easter eggs that fit the vibe.**
   - Konami sequence (↑↑↓↓←→←→BA) anywhere outside a text input triggers a code-rain overlay: ~80–96 columns of half-width katakana, each glyph carrying one of five alpha classes based on position (`--lead` / `--bright` / `--mid` / `--dim` / `--faint`) and sparse cyan / deep-green hue accents. Falls for ~6 seconds.
   - Konami works on every page; `prefers-reduced-motion` freezes the columns mid-screen instead of animating.

10. **404 as a static C-style segfault.** Served by CloudFront `CustomErrorResponse` or nginx `error_page 404`, not by FastAPI — so the page works even when the upstream is down. Renders the Odin's-eye Norse myth as a fake C traceback (`mimir.draught() → odin.see() → huginn.recall() → muninn.fetch() → yggdrasil.lookup()`), framed with `*** Error ***` markers and an `=== Backtrace ===` header. `404 NOT FOUND` in deep phosphor red with an Orbitron bloom.

11. **Re-architect the CSS for explicit cascade.** The original 1781-line `odin.css` becomes a 37-line index that declares the layer order:

    ```css
    @layer reset, tokens, base, components, pages;
    ```

    Each per-concern module imports onto a named layer (modules under `static/css/odin/`). Same-specificity surprises across files become impossible — pages always beat components, components always beat base, base always beats tokens.

12. **Document the architecture.** `docs/frontend.md` is rewritten end-to-end with a file map, the cascade explanation, the same-specificity gotcha, the favicon-regeneration recipe, and the new linter+test table noting the vm-sandbox globals (`performance`, `requestAnimationFrame`) needed by `tests/js/loadProfile.js`.

## Design vocabulary

| Element | Glyph | Where |
|---|---|---|
| Search prompt | `>` | hero + header search field, section h2s |
| Submit button frame | `[ Return ⏎ ]` | hero search submit |
| Status bar cell frame | `[KEY: value]` | sticky-bottom status bar |
| Status bar leading prompt | `$` | first column of status bar |
| Badge frame | `[ ... ]` | category badge, beta badge, finding labels |
| Citation number frame | `[1]` `[2]` ... | numbered citations |
| Wordmark sigil | trailing blinking `_` | small wordmark only |
| Section heading prompt | `>` | profile main section h2s |
| Footer separator | `//` | site footer and inline lists |
| Synthesis timestamp | `[YYYY-MM-DDThh:mmZ]` | profile byline |
| Progress segment fill | `==========` | active when filled, blank when pending |
| Progress segment separator | `·` | between stages in the bar |
| Progress active cursor | `▒` / `░` alternating | leading edge of active segment |
| Progress failed segment | `XXXXXXXXXX` | failed stage |
| Gauge rule (positive) | `······▓···` | source audit, notability |
| Gauge rule (divergent) | `──·──▓──` | sentiment, political lean |
| Gauge marker | `▓` | current value position |
| 404 error frame | `*** Error: ... ***` | 404 page body header |
| 404 backtrace frame | `=== Backtrace ===` | 404 page body backtrace |

## Palette

OKLCH-first, hex-equivalents in comments. All in `static/css/odin/_tokens.css`.

| Token | OKLCH | Hex | Role |
|---|---|---|---|
| `--bg` | `oklch(8% 0 0deg)` | `#050505` | CRT black background |
| `--surface` | `oklch(13% 0 0deg)` | `#1a1a1a` | Card / button background |
| `--surface-2` | `oklch(17% 0.02 155deg)` | green-tinted charcoal | Elevated surface, status bar |
| `--border` | `oklch(28% 0.06 155deg)` | phosphor-tinted | Borders, dividers |
| `--text` | `oklch(78% 0.20 155deg)` | dim phosphor | Body text |
| `--text-muted` | `oklch(55% 0.16 155deg)` | dimmer phosphor | Labels |
| `--primary` | `oklch(82% 0.22 155deg)` | bright phosphor | Focus, active, CTA |
| `--accent` | `oklch(72% 0.18 150deg)` | slightly hue-shifted | Secondary headings, badges |
| `--glow` | `oklch(92% 0.22 155deg)` | near-white phosphor | Hover escalation |
| `--ok` | `oklch(82% 0.22 155deg)` | same as primary | Success states |
| `--warn` | `oklch(80% 0.17 80deg)` | amber | Amber, used sparingly |
| `--danger` | `oklch(60% 0.24 18deg)` | matrix red-pill red | Errors, 404 page, finding labels (neg) |

Body and mono are Courier Prime; the wordmark and large titles are Orbitron with `font-weight: 900`. Audiowide is the fallback in case Orbitron fails to load.

## What landed

| Area | Files | Outcome |
|---|---|---|
| CSS architecture | `static/css/odin.css` (37-line index) + 13 modules under `static/css/odin/` | `@layer reset, tokens, base, components, pages`; no file > 700 lines |
| Palette | `static/css/odin/_tokens.css` | OKLCH phosphor + Courier/Orbitron fonts |
| Wordmark | `static/css/odin/_typography.css` | Orbitron bloom recipe, doubled-specificity selectors |
| Status bar | `static/css/odin/_layout.css` | Sticky-footer position, `$` prompt, bracket-framed cells, body `:has(.status-bar)` padding reserve |
| Hero | `static/css/odin/pages/_hero.css`, `src/odin/templates/index.html` | `>` prompt, `[ Return ⏎ ]` submit, hero margin, quota fade hook |
| Profile | `static/css/odin/pages/_profile.css`, `src/odin/templates/profile.html` | `>` heading prompts, bracket finding labels, `[N]` citation numbers, ASCII progress bar markup |
| Auth / dashboard / 404 | `static/css/odin/pages/_auth.css`, `_dashboard.css`, `_error.css` | Phosphor palette + Orbitron headings |
| ASCII progress | `static/js/profile.js`, `static/css/odin/_progress.css` | Single-line bar with `requestAnimationFrame` fill animation |
| ASCII gauges | `static/js/profile.js`, `static/css/odin/_gauges.css` | `gauge-line` builder for positive + divergent, marker glyph `▓` |
| Site-wide JS | `static/js/odin.js`, `src/odin/templates/_base.html` | Type-on, quota fade, Konami → code rain |
| Code rain | `static/css/odin/_effects.css` | Per-glyph alpha + hue variation, reduced-motion freeze |
| 404 page | `static/404.html`, `config/nginx.conf` | Standalone Odin's-eye-as-segfault, served by nginx via `error_page 404` (or CloudFront `CustomErrorResponse`) |
| Favicon | `static/favicon.svg`, `static/favicon-32x32.png`, `static/apple-touch-icon.png`, `static/favicon.ico` | Phosphor green eye on CRT black, raster variants regenerated via `librsvg + ImageMagick` |
| Manifest | `static/site.webmanifest` | `theme_color` + `background_color` → `#050505` |
| Templates | All Jinja templates | Title separators `·` → `//`, font URL updated to Courier Prime + Orbitron + Audiowide |
| Docs | `docs/frontend.md`, `docs/matrix-rebrand.md` (this file) | New architecture documented |
| Tests | `tests/js/profile.test.js`, `tests/js/loadProfile.js` | Rewritten end-to-end for new ASCII markup (29 tests, all green); sandbox globals expanded |
| Mockup sandbox | `mockup/`, `static/css/_mockup/` | Iteration artifacts kept as visual reference; deferred deletion |

## Validation

All gates green at the end:

- `make lint` — 0 errors, 0 warnings (ruff format/check, pyright, djlint, stylelint, eslint, markdownlint, lychee, bandit, xenon)
- `make test-unit` — 228 pytest + 29 vitest
- `make test-smoke` — all assertions passed (with new nginx 404 wiring)
- `make test-integration` — 4 passed, 1 skipped (SMTP — needs `SMTP_TEST_RECIPIENT`)
- Curl-verified: `/`, `/profile?q=anything`, `/login`, `/about`, `/privacy`, `/terms` all render 200 with new chrome; `/no-such-path-here` renders the new 404 with proper status code; static assets (`/static/css/odin.css`, `/static/js/odin.js`, `/static/404.html`, `/static/favicon.svg`) all 200.

## Decisions left for follow-up

- **Mockup sandbox deletion.** `mockup/` and `static/css/_mockup/` are kept in the tree as visual reference for the design decisions. Drop them once the rebrand merges and you've confirmed everything reads right in production.
- **Open Graph share image.** Existing TODO #5 ("Generate an Open Graph share image") still applies — the social-card image needs to be regenerated with the new palette / wordmark. Out of scope for this PR.
- **GitHub source link.** TODO low-priority #1; restoring the Octocat link should be straightforward with the new bracket-badge styling.
- **JS tests for `odin.js` itself.** Currently only `profile.js` has vitest coverage. The new `odin.js` (type-on, Konami, quota fade) has no unit tests; the existing test harness in `tests/js/loadProfile.js` could be adapted.
- **CloudFront `CustomErrorResponse` config.** The dev nginx is wired to serve `static/404.html` on 404s. The production CloudFront distribution needs a matching `CustomErrorResponse` entry (or rely on nginx for prod too). Decide before the next deploy.
- **Visual contrast audit.** Body text (`--text` over `--bg`) is roughly 11:1; primary phosphor over background is roughly 13:1. AA-pass everywhere checked. A formal contrast audit with a tool like `axe` / `pa11y` would be belt-and-suspenders.

## Picking up from another machine

```sh
git fetch origin
git switch worktree-matrix-rebrand
# Bring up dev with your own env keys:
SECRET_KEY=… APP_URL=http://localhost:8000 make dev
# Pages to eyeball at http://localhost:8000:
#   /                       hero
#   /profile?q=ada%20lovelace  profile (watch the ASCII progress + ASCII gauges animate)
#   /login                  sign-in
#   /no-such-path           Odin's-eye 404
# Optional: hit ↑↑↓↓←→←→BA anywhere to trigger code rain
make down                    # stop the stack when done
```

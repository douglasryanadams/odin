# Coding Standards

The rubric for *how* we write code in this repo. The hard process requirements (write tests first, run `make lint`, run `make test`) live in [`CLAUDE.md`](../CLAUDE.md).

## Expectations

- Define validation criteria before pursuing a task; execute them before calling it done.
- Prefer iteration over complete solutions — find the smallest increment.
- Think thoroughly; output concisely.
- Write commit subject lines that read well in `git log`.

## Software development principles

- Prefer composition over inheritance.
- Prefer dependency injection over tight coupling.
- Prefer functional programming over OOP — plain functions and pydantic/dataclass models beat classes with hidden state.
- Prioritize readability over performance.
- Prioritize clarity over comments.
- Only mock third-party dependencies — not our own code.
- Review computational and memory complexity at design time.
- Only rely on Pydantic models for HTTP interfaces, use `dataclass` with `frozen=True` for other cases

## SOLID

- **S**ingle responsibility — one reason to change per module/function.
- **O**pen/closed — open for extension, closed for modification.
- **L**iskov substitution — subtypes must behave like their parents.
- **I**nterface segregation — small interfaces beat large ones.
- **D**ependency inversion — depend on abstractions, not concretions.

## JavaScript and CSS

The same rubric applies to the front-end. Vanilla JS, vanilla CSS, no framework, no build step. Lint with `eslint` + `stylelint`; test with `vitest` (happy-dom). All of these run inside the `node` sidecar via `make lint` / `make test`.

### JavaScript

- Plain functions over classes — mirror the Python "functional over OOP" preference. `profile.js` is a script-global file of pure helpers; keep it that way.
- Pass dependencies in as arguments. The DOM is a dependency: helpers should take elements / values, not reach for module-level globals.
- One responsibility per function. If a helper both builds DOM and decides routing, split it.
- Build DOM with `document.createElement` + `textContent`. Never `innerHTML`, never string concatenation into the DOM — AI / network text is untrusted by default.
- Prefer `const`. Use `let` only when reassignment is the simplest expression. Never `var`.
- `===` / `!==` only. Explicit is better than implicit.
- Errors should never pass silently — surface them to the UI (`is-failed` state, summary replacement) or `console.error`. Don't swallow with empty `catch`.
- Comments explain *why*, not *what*. Identifier names carry the *what*.
- No new runtime dependencies without discussion. The browser ships a capable standard library.

### CSS

- BEM class naming, enforced by stylelint: `block`, `block__element`, `block--modifier`. State classes (`is-active`, `is-done`, `is-failed`) toggle independently of structural classes.
- Theme tokens live as custom properties on `:root`. Reach for a token before introducing a literal color or font.
- Layout via the existing 12-column grid (`card--span-6` / `card--span-12`); add a new utility only when reuse justifies it.

### Templates (Jinja2)

- `djlint` with the `jinja` profile is the source of truth for HTML formatting (2-space indent, 100-char lines).
- Escape AI / user content. Never bypass autoescape with `| safe` for untrusted text.

### Testing the front-end

- Vitest runs in `tests/js/`. The `loadProfile` harness reads `profile.js` and runs it inside a `node:vm` context with happy-dom globals — that is what lets a script-global file expose helpers to tests without an `export` keyword.
- Cover happy paths, fallback branches, and no-op invalid input — the same shape as the pytest suite. Mock only external boundaries (`EventSource`); don't mock our own helpers.
- If `profile.js` ever moves to ES modules, replace the `vm` harness with a direct dynamic import — don't grow the harness.

## Zen of Python

- Beautiful is better than ugly.
- Explicit is better than implicit.
- Simple is better than complex.
- Complex is better than complicated.
- Flat is better than nested.
- Sparse is better than dense.
- Readability counts.
- Special cases aren't special enough to break the rules.
- Although practicality beats purity.
- Errors should never pass silently.
- Unless explicitly silenced.
- In the face of ambiguity, refuse the temptation to guess.
- There should be one — and preferably only one — obvious way to do it.
- Although that way may not be obvious at first unless you're Dutch.
- Now is better than never.
- Although never is often better than *right* now.
- If the implementation is hard to explain, it's a bad idea.
- If the implementation is easy to explain, it may be a good idea.
- Namespaces are one honking great idea — let's do more of those!

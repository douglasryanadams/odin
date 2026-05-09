# IMPORTANT REQUIREMENTS

- Before you make a change to the code, write a test for the change you plan. Confirm this test with me before implementing the feature.
- Run `make lint`; it must pass before the task is done.
- Run `make test`; it must pass before the task is done.

# Absolute prohibitions

- Never write display borders (e.g. `────────────`) anywhere in the project — not in source files, comments, CSS, templates, scripts, documentation, git commit messages, or pull request messages. They are terminal UI artifacts and have no place in committed code.

# Process expectations

- Define validation criteria before pursuing each task; execute it before marking complete.
- Identify the smallest increment of work; prefer iteration over complete solutions.
- Think thoroughly; keep output concise.
- Write git commit subjects that make history easy to read. Do not use dashes to decorate commit messages.
- When adding new components, dependencies, or tools, review existing documentation and update it as needed. When unsure what to add, ask.

# Configuration defaults

- Default to production values. Configuration defaults should be the safe production setting (e.g., `cookie_secure=True`, HSTS enabled, strict CSP). Local-dev overrides go in `.env` or test fixtures, not in the code default. The reason: a forgotten or unset env var should fail closed, not insecure.

# Testing standards

- Never pass a fixture as a parameter purely for its side effects. The `del fixture_name` pattern is a symptom of this — avoid it.
- For shared setup that applies to all tests in a module, use `autouse=True` fixtures.
- For per-test setup, call helper functions explicitly in the test body.

# Third-party type stubs

When a library has no bundled types and no `types-*` package on PyPI, create a minimal `.pyi` stub in `stubs/<package>/` covering only the symbols we actually use. Configure pyright to find it with `stubPath = "stubs"` in `[tool.pyright]`. This is preferable to scattered `cast()` calls or `# pyright: ignore` suppressions.

# Coding standards & project orientation

The full rubric (composition, DI, FP, SOLID, Zen of Python) lives in [`docs/coding-standards.md`](./docs/coding-standards.md).

For prose in documentation, summaries, and commit messages, follow [`docs/prose-style.md`](./docs/prose-style.md).

For design decisions — naming, function design, class structure, error handling, and testing — follow [`docs/clean-code.md`](./docs/clean-code.md).

For "where do I find what" in the codebase — back-end, front-end, configuration, SearXNG, the Anthropic API — start at [`docs/README.md`](./docs/README.md).

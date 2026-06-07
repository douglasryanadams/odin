---
name: pre-commit-check
description: This skill should be used before committing any change to the ODIN repo, including one-line or asset-only changes, to run the right subset of make lint and make test, work around port conflicts from parallel worktree stacks, and tear down whatever it started. Use when the user says "run lint and tests", "is this ready to commit", "verify before I commit", or whenever CLAUDE.md's "make lint must pass / make test must pass" requirement needs checking.
---

# Pre-commit check for ODIN

ODIN's checks run inside Docker via `make lint` and `make test`. Two things
make this trickier than "just run the make targets":

- **Parallel worktrees collide on ports.** Several sessions often run compose
  stacks at once, and `make lint` / `make test` fail at the `docker compose
  run` step if another worktree's `odin-postgres` already holds
  `127.0.0.1:5432` (or `odin-web` holds `8080`). The fix is `--no-deps`
  invocations that skip starting postgres/valkey entirely.
- **A one-line change doesn't need the full matrix.** Scope the run to what
  actually changed.

## Procedure

1. **Scope to what changed.** Run `git status --porcelain` and
   `git diff --stat`, then map paths to checks:
   - `src/**/*.py` → `ruff check`, `ruff format --check`, `pyright`, `xenon`,
     `bandit`, `pytest` (`test-unit`)
   - `static/js/**` → `eslint`, `vitest` (`test-js`)
   - `static/css/**` → `stylelint`
   - `src/odin/templates/**` → `djlint`
   - any `*.md` → `lint-markdown`, `lint-links`
   - changes touching request handling, auth, or migrations → also
     `test-integration`

   Don't skip checks because a change "looks safe" — CLAUDE.md requires
   `make lint` and `make test` to pass before a task is done, and that
   applies per commit, including asset-only changes.

2. **Check for a port conflict before invoking `make`.** Run:

   ```bash
   docker ps --format '{{.Names}}: {{.Ports}}'
   ```

   If you see another worktree's `*-odin-postgres-1` bound to
   `127.0.0.1:5432->5432/tcp` (or `*-odin-web-1` on `8080`), `make lint` /
   `make test` will fail trying to start their own copies. Skip straight to
   step 4.

3. **No conflict: run the `make` targets directly.** Use the narrowest target
   that covers what changed — e.g. `make lint-markdown` for a docs-only edit,
   `make test-unit` for a Python change with no template/integration impact,
   or the full `make lint` / `make test` for broad changes.

4. **Conflict: fall back to `--no-deps` invocations**, mirroring the targets
   in `Makefile` but skipping dependency startup:

   ```bash
   docker compose --project-directory . -f compose/docker-compose.yml \
     -f compose/docker-compose.override.yml run --rm --no-deps web \
     uv run ruff check .
   ```

   Swap the trailing command for each check you need
   (`ruff format --check .`, `pyright`, `xenon --max-absolute B
   --max-modules A --max-average A src/`, `bandit -r src/ -c pyproject.toml`,
   `pytest`, `djlint src/odin/templates --check`). For JS/CSS/markdown
   checks, use `--no-deps node` the same way (`npx eslint ...`,
   `npx stylelint ...`, `npx markdownlint-cli2 ...`). `--no-deps` is the only
   change needed — the rest of each command line matches its `make` target
   verbatim, so check `Makefile` if a target's exact invocation is unclear.

5. **Tear down what you started.** If you brought up `odin-postgres` /
   `odin-valkey` (only `test-integration` does this via `up -d --wait`), run
   `make down` or `docker compose ... down --remove-orphans` so other
   worktrees aren't blocked behind your held ports.

6. **Report pass/fail per category** — lint, types, security, unit tests,
   integration tests, markdown — not just a single go/no-go. That tells the
   user exactly what to fix if something fails, and confirms what already
   passed so they don't re-run it needlessly.

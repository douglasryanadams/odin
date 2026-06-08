---
name: commit-and-open-pr
description: This skill should be used when the user wants to commit changes and open a pull request for ODIN — phrases like "commit this and open a PR", "ship this", "create a PR for this branch", or "let's get this merged". Chains the pre-commit-check skill first since CLAUDE.md requires make lint and make test to pass before a commit, checks whether TODO.md needs updating in the same change, and drafts the commit message and PR body in this repo's established style before running gh pr create.
---

# Commit and open a PR for ODIN

Only run this when the user has explicitly asked to commit, push, or open a
PR. These actions are visible to others and hard to undo. One approval covers
this run only — ask again next time.

## Procedure

1. **Run `pre-commit-check` first**, or confirm it has just run clean.
   CLAUDE.md says `make lint` and `make test` must pass before a task is
   done. That rule applies to every commit. Never commit on top of a failing
   or unverified check.

2. **Check whether TODO.md needs an update.** Does the diff finish, rescope,
   or replace a tracked item? If so, update `TODO.md` in the same commit:
   drop finished items, re-rank within High/Medium/Low, and fix any
   cross-references that are now stale. Recent examples: `d405b71`, `b77c2b7`.

3. **Draft the commit message in this repo's own style.** `git log --oneline`
   is the source of truth. Recent subjects read like "Add bounded retries
   with backoff around Claude calls" and "Fix citation URL lookup, add
   empty-content guardrail, bump cache key". Follow these rules:
   - Subject: imperative present tense (Add/Fix/Drop/Surface/Restyle), under
     about 70 characters, **no dashes used to decorate the message**
   - Say *why* the change was made, not *what* changed — the diff already
     shows what changed
   - Stage specific files by name. Never `git add -A` or `git add .`
   - Never stage files that look like secrets, such as `.env` or
     `credentials.json`
   - End the message with
     `Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>`

4. **Push the branch.** Worktree branches often haven't been pushed yet.
   Check with `git status` and `git rev-parse --abbrev-ref
   --symbolic-full-name @{u}`, and add `-u` on the first push.

5. **Draft the PR using this repo's actual template.** Run
   `gh pr view 55 --json body -q .body` to see a full example. Then:
   - Keep the title under 70 characters, in the same imperative style as
     commit subjects
   - Write a `## Summary` section as bullet points. Each bullet should say
     *why* that change was made, and name the `TODO.md` item it resolves or
     rescopes when there is one
   - Add a `## Test plan` checklist: the tests you added or ran, plus
     confirmation that `make lint` and `make test` pass
   - End with the footer
     `🤖 Generated with [Claude Code](https://claude.com/claude-code)`
   - Small maintenance changes can ship with an empty body — several merged
     PRs here did (#50, #56, #57, #58). Match the body's weight to the
     change's weight. Don't pad a one-line fix into a five-bullet essay.

6. **Create the PR and report back.** Use
   `gh pr create --title "..." --body "$(cat <<'EOF' ... EOF)"` — the heredoc
   keeps the formatting intact. Then give the user the PR URL.

## Don'ts

- Don't force-push, amend a published commit, or skip hooks (`--no-verify`,
  `--no-gpg-sign`) unless the user explicitly asks for it.
- Don't push straight to `main`, and don't merge the PR. Opening it is where
  this skill's job ends.
- Don't guess at the Summary or Test plan. Base both on the real diff and the
  checks that actually ran in step 1.

---
name: user-architect-preferences
description: Architect preferences for platform decisions — cost-first, low lock-in, dev/prod parity required, hobby-scale economics
metadata:
  type: user
---

Platform decision preferences established from odin project context:

- Cost-consciousness is the top priority; this is a hobby project, free to users, no revenue to offset AWS spend
- Strong preference for options that don't die with the app layer (resilience/decoupling goal)
- Wants SQL-style ad-hoc query access to operational data (reporting goal) — not comfortable digging through hashed Redis keys via CLI
- Hard rule: dev and prod stacks must stay in parity — no env-only paths or standalone uvicorn shortcuts
- Accepts managed AWS services when operational leverage is real; not opposed to self-hosted containers when cost is dramatically better
- Low lock-in preferred for early-stage decisions; standard Postgres and S3-compatible storage are natural fits
- No tolerance for over-engineering: recommending enterprise patterns for hobby scale will be rejected

[[project-odin-platform]]

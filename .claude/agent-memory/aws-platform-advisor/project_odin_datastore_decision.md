---
name: project-odin-datastore-decision
description: May 2026 datastore architecture analysis — hybrid ValKey (ephemeral) + RDS Postgres t4g.micro (durable) recommended over full DynamoDB or Aurora
metadata:
  type: project
---

Analysis performed 2026-05-25. Architect asked for decision-grade comparison of ValKey (status quo), DynamoDB, and Aurora/RDS Postgres.

Primary recommendation: Keep ValKey for ephemeral/cache data (items 1-4) + add RDS PostgreSQL on db.t4g.micro for durable data (history, user signups).

Runner-up: Replace ValKey entirely with DynamoDB (simpler ops, no container to manage) if the architect is comfortable with DynamoDB's query model for history and can tolerate verbose ad-hoc reporting.

Pricing confirmed (us-west-2, May 2026 estimates):

- RDS Postgres db.t4g.micro: ~$0.016-$0.018/hr on-demand → ~$13-14/mo + 20 GB gp2 storage ~$2.30/mo = ~$15-16/mo added cost
- Aurora Serverless v2: $0.12/ACU-hr, scales to zero (announced late 2024, GA April 2026); 15s cold start resume; storage $0.10/GB-mo; minimum when active ~0.5 ACU = $43/mo if not paused; impractical for hobby unless always paused
- ElastiCache Serverless (Valkey): $0.084/GB-hr storage + $0.0023/million ECPU; 100MB minimum = ~$6/mo floor; node-based cache.t4g.micro is cheaper at ~$11-13/mo but requires VPC peering or same VPC
- DynamoDB on-demand: $1.25/million WRU, $0.25/million RRU; at hobby scale effectively $0-1/mo for data ops; but no SQL for ad-hoc queries

Key insight: data splits naturally into two tiers:

1. Ephemeral/TTL-native: nonces, rate-limit counters, profile cache — best in Valkey; fighting SQL TTL eviction is not worth it
2. Durable/queryable: search history (item 5) + missing signup records — best in Postgres

Dev/prod parity note: Postgres container (dev) ↔ RDS (prod) is clean parity. ValKey container stays unchanged in both envs.

**Why:** Cost-consciousness is top priority. Architect explicitly wants (a) resilience if app layer dies, (b) easy ad-hoc SQL reporting (who signed up, usage stats).
**How to apply:** When advising on future data features, assume hybrid ValKey+Postgres as baseline. Default new durable data to Postgres, new ephemeral/TTL data to ValKey.

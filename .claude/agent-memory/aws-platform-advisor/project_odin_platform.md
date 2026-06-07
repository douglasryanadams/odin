---
name: project-odin-platform
description: Odin current infrastructure — EC2 t4g.small, Docker Compose, ValKey, CloudFront, no relational DB as of May 2026
metadata:
  type: project
---

Current production stack as of 2026-05-25:

- Compute: single EC2 t4g.small (Arm, Amazon Linux 2023, us-west-2) ~$12/mo
- Runtime: docker-compose with three containers: web (FastAPI+Gunicorn), nginx, odin-valkey (Valkey 9.0.4)
- Edge: CloudFront free tier + Route53 + ACM; EC2 security group locks port 8000 to CloudFront prefix list only
- Secrets: AWS Secrets Manager, single secret `odin/app`
- Deploy: GitHub Actions → ECR → SSM send-command → scripts/deploy.sh → docker compose up
- Admin access: SSM Session Manager only; no SSH
- Storage: ValKey RDB snapshots to Docker named volume on 20 GiB gp3 EBS; daily AWS Backup (7-day retention)
- No relational database; no user/account table; no signup record
- Auth: passwordless magic-link → HMAC-signed session cookie (email + 30-day expiry); emails hashed (sha256, 16-char prefix) in ValKey keys

Key abstraction files:

- src/odin/store.py — rate limiting, history, nonces
- src/odin/cache.py — profile result cache

**Why:** Hobby project, free to users, built lean. No traffic metrics. Single ValKey node, no clustering.
**How to apply:** Recommendations must fit hobby-scale economics. Never over-engineer for scale that doesn't exist.

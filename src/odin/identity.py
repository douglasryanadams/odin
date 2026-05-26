"""Stable, anonymized identity hashing shared across datastores.

The same truncated SHA-256 keys a user in ValKey (rate limits) and Postgres
(signups, search history). One canonical function keeps those views consistent
and keeps raw email addresses out of every store.
"""

import hashlib


def hash_email(email: str) -> str:
    """Return the lowercased email's SHA-256 hex digest, truncated to 16 chars."""
    return hashlib.sha256(email.lower().encode()).hexdigest()[:16]

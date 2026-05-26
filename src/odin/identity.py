"""Stable, anonymized identity hashing shared across datastores.

The same truncated SHA-256 keys a user in ValKey (rate limits) and Postgres
(signups, search history). One canonical function keeps those views consistent
and keeps raw email addresses out of every store.
"""

import hashlib
from dataclasses import dataclass


def hash_email(email: str) -> str:
    """Return the lowercased email's SHA-256 hex digest, truncated to 16 chars."""
    return hashlib.sha256(email.lower().encode()).hexdigest()[:16]


@dataclass(frozen=True, slots=True)
class Requester:
    """Who is making a request: a signed-in email, or an anonymous cookie + IP.

    Bundles the identity that rate limiting and history keying both need so it
    travels as one argument. The user-vs-anonymous branch stays in the functions
    that consume it, not here.
    """

    user_email: str | None
    cookie_id: str
    ip_address: str

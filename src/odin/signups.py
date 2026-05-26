"""Anonymized signup records: a durable, queryable log of site usage.

A row is keyed by the same hashed identity used elsewhere, so no raw email is
ever stored. ``record_signup`` fires on every successful magic-link verification
and doubles as first-seen / last-seen tracking, which is what the reporting
helpers summarize.
"""

import datetime

import asyncpg

from odin.identity import hash_email

_UPSERT = """
    INSERT INTO signups (email_hash) VALUES ($1)
    ON CONFLICT (email_hash)
    DO UPDATE SET last_seen = now(), login_count = signups.login_count + 1
"""


async def record_signup(pool: asyncpg.Pool, email: str) -> None:
    """Record a verified sign-in: insert on first sight, else advance the row.

    On a repeat sign-in the existing ``first_seen`` is preserved while
    ``last_seen`` moves forward and ``login_count`` increments.
    """
    await pool.execute(_UPSERT, hash_email(email))


async def total_signups(pool: asyncpg.Pool) -> int:
    """Return the total number of distinct signups."""
    return await pool.fetchval("SELECT count(*) FROM signups")


async def count_since(pool: asyncpg.Pool, since: datetime.datetime) -> int:
    """Return the number of signups first seen at or after ``since``."""
    return await pool.fetchval("SELECT count(*) FROM signups WHERE first_seen >= $1", since)


async def returning_count(pool: asyncpg.Pool) -> int:
    """Return the number of signups that have signed in more than once."""
    return await pool.fetchval("SELECT count(*) FROM signups WHERE login_count > 1")


async def delete_signup(pool: asyncpg.Pool, email: str) -> None:
    """Remove the signup row for an email, on account deletion."""
    await pool.execute("DELETE FROM signups WHERE email_hash = $1", hash_email(email))

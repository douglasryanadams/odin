"""Postgres-backed search history.

A search is stored as a single row carrying whichever identifiers apply: the
hashed email for signed-in users, or the cookie id and IP for anonymous ones.
Anonymous reads match either identifier with a plain OR, so clearing one still
surfaces history via the other; the ValKey version had to dual-write and
deduplicate to get the same effect.
"""

import asyncpg

from odin.identity import Requester, hash_email

_DEFAULT_HISTORY_COUNT = 20


async def push_history(
    pool: asyncpg.Pool, requester: Requester, *, query: str, category: str
) -> None:
    """Append a search to the requester's history as a single row."""
    if requester.user_email:
        await pool.execute(
            "INSERT INTO search_history (email_hash, query, category) VALUES ($1, $2, $3)",
            hash_email(requester.user_email),
            query,
            category,
        )
    else:
        await pool.execute(
            "INSERT INTO search_history (cookie_id, ip, query, category) VALUES ($1, $2, $3, $4)",
            requester.cookie_id,
            requester.ip_address,
            query,
            category,
        )


async def get_history(
    pool: asyncpg.Pool, requester: Requester, *, count: int = _DEFAULT_HISTORY_COUNT
) -> list[dict[str, str]]:
    """Return the requester's most recent searches, newest first.

    Anonymous history matches either the cookie or the IP, so a visitor who
    changes one identifier still sees prior searches via the other.
    """
    if requester.user_email:
        rows = await pool.fetch(
            "SELECT query, category, created_at FROM search_history "
            "WHERE email_hash = $1 ORDER BY created_at DESC LIMIT $2",
            hash_email(requester.user_email),
            count,
        )
    else:
        rows = await pool.fetch(
            "SELECT query, category, created_at FROM search_history "
            "WHERE cookie_id = $1 OR ip = $2 ORDER BY created_at DESC LIMIT $3",
            requester.cookie_id,
            requester.ip_address,
            count,
        )
    return [
        {"q": row["query"], "t": row["created_at"].isoformat(), "cat": row["category"]}
        for row in rows
    ]


async def delete_user_history(pool: asyncpg.Pool, email: str) -> None:
    """Remove a signed-in user's search history on account deletion.

    Anonymous rows carry no email_hash and are left untouched.
    """
    await pool.execute("DELETE FROM search_history WHERE email_hash = $1", hash_email(email))

"""Integration tests for the signups store against a real Postgres."""

import datetime

import asyncpg
import pytest

from odin import signups
from odin.identity import hash_email

pytestmark = pytest.mark.integration


async def test_record_signup_inserts_new_row(db_pool: asyncpg.Pool) -> None:
    await signups.record_signup(db_pool, "user@example.com")

    row = await db_pool.fetchrow(
        "SELECT * FROM signups WHERE email_hash = $1", hash_email("user@example.com")
    )
    assert row is not None
    assert row["login_count"] == 1
    assert row["first_seen"] is not None
    assert row["last_seen"] is not None


async def test_record_signup_is_idempotent_and_advances(db_pool: asyncpg.Pool) -> None:
    email = "user@example.com"
    await signups.record_signup(db_pool, email)
    first = await db_pool.fetchrow(
        "SELECT first_seen, last_seen, login_count FROM signups WHERE email_hash = $1",
        hash_email(email),
    )

    await signups.record_signup(db_pool, email)
    second = await db_pool.fetchrow(
        "SELECT first_seen, last_seen, login_count FROM signups WHERE email_hash = $1",
        hash_email(email),
    )

    assert second["first_seen"] == first["first_seen"]  # preserved on repeat
    assert second["last_seen"] >= first["last_seen"]  # advanced
    assert second["login_count"] == 2
    assert await signups.total_signups(db_pool) == 1  # still one row


async def test_record_signup_stores_only_the_hash(db_pool: asyncpg.Pool) -> None:
    email = "Someone@Example.COM"
    await signups.record_signup(db_pool, email)

    stored = await db_pool.fetchval("SELECT email_hash FROM signups")
    assert stored == hash_email(email)
    assert "@" not in stored
    assert email.lower() not in stored


async def test_reporting_counts(db_pool: asyncpg.Pool) -> None:
    await signups.record_signup(db_pool, "a@example.com")
    await signups.record_signup(db_pool, "b@example.com")
    await signups.record_signup(db_pool, "a@example.com")  # a signs in again

    assert await signups.total_signups(db_pool) == 2
    assert await signups.returning_count(db_pool) == 1  # only a has signed in twice

    now = datetime.datetime.now(datetime.UTC)
    assert await signups.count_since(db_pool, now - datetime.timedelta(hours=1)) == 2
    assert await signups.count_since(db_pool, now + datetime.timedelta(hours=1)) == 0


async def test_delete_signup_removes_the_row(db_pool: asyncpg.Pool) -> None:
    await signups.record_signup(db_pool, "a@example.com")
    await signups.record_signup(db_pool, "b@example.com")

    await signups.delete_signup(db_pool, "a@example.com")

    assert await signups.total_signups(db_pool) == 1  # only b remains

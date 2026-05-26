"""Integration tests for the search-history store against a real Postgres."""

import asyncpg
import pytest

from odin import history
from odin.identity import Requester

pytestmark = pytest.mark.integration

_USER = Requester("u@example.com", "", "")


async def test_user_push_and_get_roundtrip(db_pool: asyncpg.Pool) -> None:
    await history.push_history(db_pool, _USER, query="einstein", category="person")
    entries = await history.get_history(db_pool, _USER)
    assert len(entries) == 1
    assert entries[0]["q"] == "einstein"
    assert entries[0]["cat"] == "person"
    assert entries[0]["t"]  # ISO timestamp present


async def test_anon_history_single_row_found_by_cookie_or_ip(db_pool: asyncpg.Pool) -> None:
    await history.push_history(
        db_pool, Requester(None, "cookieA", "1.2.3.4"), query="q1", category="other"
    )
    # The relational model stores one row, not one per identifier.
    assert await db_pool.fetchval("SELECT count(*) FROM search_history") == 1

    by_cookie = await history.get_history(db_pool, Requester(None, "cookieA", "9.9.9.9"))
    by_ip = await history.get_history(db_pool, Requester(None, "other", "1.2.3.4"))
    assert [e["q"] for e in by_cookie] == ["q1"]
    assert [e["q"] for e in by_ip] == ["q1"]


async def test_anon_history_not_duplicated_when_both_identifiers_match(
    db_pool: asyncpg.Pool,
) -> None:
    anon = Requester(None, "c", "1.2.3.4")
    await history.push_history(db_pool, anon, query="q1", category="other")
    entries = await history.get_history(db_pool, anon)
    assert [e["q"] for e in entries] == ["q1"]  # single row, no OR-match duplication


async def test_get_history_orders_recent_first_and_limits(db_pool: asyncpg.Pool) -> None:
    for i in range(3):
        await history.push_history(db_pool, _USER, query=f"q{i}", category="other")
    entries = await history.get_history(db_pool, _USER, count=2)
    assert [e["q"] for e in entries] == ["q2", "q1"]  # newest first, capped at the limit


async def test_delete_user_history_removes_only_that_user(db_pool: asyncpg.Pool) -> None:
    other_user = Requester("b@example.com", "", "")
    anon = Requester(None, "cookie", "1.2.3.4")
    await history.push_history(db_pool, _USER, query="a-query", category="other")
    await history.push_history(db_pool, other_user, query="b-query", category="other")
    await history.push_history(db_pool, anon, query="anon-query", category="other")

    await history.delete_user_history(db_pool, "u@example.com")

    remaining = {r["query"] for r in await db_pool.fetch("SELECT query FROM search_history")}
    assert remaining == {"b-query", "anon-query"}  # other user's and anonymous rows untouched

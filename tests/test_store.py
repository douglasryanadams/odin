"""Tests for Valkey-backed rate limiting and history store."""

from unittest.mock import AsyncMock, patch

import pytest

from odin import store


@pytest.fixture
def valkey() -> AsyncMock:
    client = AsyncMock()
    client.get.return_value = None
    client.incr.return_value = 1
    client.lrange.return_value = []
    return client


async def test_get_query_count_returns_zero_when_unset(valkey: AsyncMock) -> None:
    valkey.get.return_value = None
    assert await store.get_query_count(valkey, "some-key") == 0


async def test_get_query_count_returns_stored_value(valkey: AsyncMock) -> None:
    valkey.get.return_value = b"7"
    assert await store.get_query_count(valkey, "some-key") == 7


async def test_record_query_increments_both_anon_keys(valkey: AsyncMock) -> None:
    with patch("odin.store._today_utc", return_value="2024-01-01"):
        await store.record_query(valkey, user_email=None, cookie_id="abc", ip_address="1.2.3.4")
    keys = [c.args[0] for c in valkey.incr.call_args_list]
    assert "rate:anon:abc:2024-01-01" in keys
    assert "rate:anon:1.2.3.4:2024-01-01" in keys


async def test_record_query_increments_only_user_key_when_logged_in(valkey: AsyncMock) -> None:
    with patch("odin.store._today_utc", return_value="2024-01-01"):
        await store.record_query(
            valkey, user_email="user@example.com", cookie_id="abc", ip_address="1.2.3.4"
        )
    keys = [c.args[0] for c in valkey.incr.call_args_list]
    assert len(keys) == 1
    assert keys[0].startswith("rate:user:")


@pytest.mark.parametrize(
    ("count_bytes", "expected"),
    [
        (b"2", False),  # under limit
        (b"3", True),  # at limit
        (b"4", True),  # over limit
    ],
)
async def test_is_rate_limited_anon_by_count(
    valkey: AsyncMock,
    count_bytes: bytes,
    expected: bool,  # noqa: FBT001
) -> None:
    valkey.get.return_value = count_bytes
    result = await store.is_rate_limited(
        valkey,
        user_email=None,
        cookie_id="abc",
        ip_address="1.2.3.4",
        anon_limit=3,
        auth_limit=20,
    )
    assert result is expected


async def test_is_rate_limited_triggers_on_ip_even_if_cookie_is_under(valkey: AsyncMock) -> None:
    valkey.get.side_effect = [b"1", b"3"]  # cookie=1, ip=3 (at limit)
    result = await store.is_rate_limited(
        valkey,
        user_email=None,
        cookie_id="abc",
        ip_address="1.2.3.4",
        anon_limit=3,
        auth_limit=20,
    )
    assert result is True


@pytest.mark.parametrize("expected_key", ["history:anon:abc", "history:anon:1.2.3.4"])
async def test_push_history_anon_writes_to_both_keys(valkey: AsyncMock, expected_key: str) -> None:
    await store.push_history(
        valkey,
        user_email=None,
        cookie_id="abc",
        ip_address="1.2.3.4",
        entry={"q": "test", "t": "now", "cat": "person"},
    )
    lpush_keys = [c.args[0] for c in valkey.lpush.call_args_list]
    assert expected_key in lpush_keys


async def test_push_history_anon_sets_ttl_on_both_keys(valkey: AsyncMock) -> None:
    await store.push_history(
        valkey,
        user_email=None,
        cookie_id="abc",
        ip_address="1.2.3.4",
        entry={"q": "test", "t": "now", "cat": "person"},
    )
    assert valkey.expire.call_count == 2


async def test_push_history_user_writes_to_single_key_with_ninety_day_ttl(
    valkey: AsyncMock,
) -> None:
    await store.push_history(
        valkey,
        user_email="u@example.com",
        cookie_id="abc",
        ip_address="1.2.3.4",
        entry={"q": "test", "t": "now", "cat": "person"},
    )
    assert valkey.lpush.call_count == 1
    valkey.expire.assert_called_once()
    args = valkey.expire.call_args.args
    assert args[0].startswith("history:user:")
    assert args[1] == 90 * 24 * 60 * 60


async def test_get_history_merges_and_deduplicates_anon_keys(valkey: AsyncMock) -> None:
    shared = b'{"q": "shared", "t": "2024-01-01", "cat": "person"}'
    cookie_only = b'{"q": "cookie-only", "t": "2024-01-02", "cat": "place"}'
    ip_only = b'{"q": "ip-only", "t": "2024-01-03", "cat": "event"}'
    valkey.lrange.side_effect = [[shared, cookie_only], [shared, ip_only]]

    history = await store.get_history(
        valkey, user_email=None, cookie_id="abc", ip_address="1.2.3.4"
    )

    queries = [e["q"] for e in history]
    assert queries.count("shared") == 1
    assert "cookie-only" in queries
    assert "ip-only" in queries


async def test_get_history_deserializes_user_entries(valkey: AsyncMock) -> None:
    valkey.lrange.return_value = [
        b'{"q": "foo", "t": "2024-01-01", "cat": "person"}',
        b'{"q": "bar", "t": "2024-01-02", "cat": "place"}',
    ]
    history = await store.get_history(
        valkey, user_email="u@example.com", cookie_id="abc", ip_address="1.2.3.4"
    )
    assert len(history) == 2
    assert history[0]["q"] == "foo"


async def test_get_history_skips_malformed_entries(valkey: AsyncMock) -> None:
    valkey.lrange.return_value = [b"not-json", b'{"q": "ok"}']
    history = await store.get_history(
        valkey, user_email="u@example.com", cookie_id="abc", ip_address="1.2.3.4"
    )
    assert len(history) == 1
    assert history[0]["q"] == "ok"

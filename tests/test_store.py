"""Tests for Valkey-backed rate limiting and magic-link nonces."""

from unittest.mock import AsyncMock, patch

import pytest

from odin import store
from odin.identity import Requester


@pytest.fixture
def valkey() -> AsyncMock:
    client = AsyncMock()
    client.get.return_value = None
    client.incr.return_value = 1
    return client


async def test_get_query_count_returns_zero_when_unset(valkey: AsyncMock) -> None:
    valkey.get.return_value = None
    assert await store.get_query_count(valkey, "some-key") == 0


async def test_get_query_count_returns_stored_value(valkey: AsyncMock) -> None:
    valkey.get.return_value = b"7"
    assert await store.get_query_count(valkey, "some-key") == 7


async def test_record_query_increments_both_anon_keys(valkey: AsyncMock) -> None:
    with patch("odin.store._today_utc", return_value="2024-01-01"):
        await store.record_query(valkey, Requester(None, "abc", "1.2.3.4"))
    keys = [c.args[0] for c in valkey.incr.call_args_list]
    assert "rate:anon:abc:2024-01-01" in keys
    assert "rate:anon:1.2.3.4:2024-01-01" in keys


async def test_record_query_increments_only_user_key_when_logged_in(valkey: AsyncMock) -> None:
    with patch("odin.store._today_utc", return_value="2024-01-01"):
        await store.record_query(valkey, Requester("user@example.com", "abc", "1.2.3.4"))
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
        valkey, Requester(None, "abc", "1.2.3.4"), anon_limit=3, auth_limit=20
    )
    assert result is expected


async def test_is_rate_limited_triggers_on_ip_even_if_cookie_is_under(valkey: AsyncMock) -> None:
    valkey.get.side_effect = [b"1", b"3"]  # cookie=1, ip=3 (at limit)
    result = await store.is_rate_limited(
        valkey, Requester(None, "abc", "1.2.3.4"), anon_limit=3, auth_limit=20
    )
    assert result is True

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


async def test_is_ip_denied_returns_false_when_not_denied(valkey: AsyncMock) -> None:
    valkey.sismember.return_value = False
    assert await store.is_ip_denied(valkey, "1.2.3.4") is False


async def test_is_ip_denied_returns_true_for_exact_match(valkey: AsyncMock) -> None:
    valkey.sismember.return_value = True
    assert await store.is_ip_denied(valkey, "1.2.3.4") is True


async def test_deny_ip_adds_to_the_denylist_set(valkey: AsyncMock) -> None:
    await store.deny_ip(valkey, "1.2.3.4")
    valkey.sadd.assert_called_once_with("denylist:ips", "1.2.3.4")


async def test_deny_ip_rejects_input_that_is_not_an_ip(valkey: AsyncMock) -> None:
    with pytest.raises(ValueError, match="does not appear to be"):
        await store.deny_ip(valkey, "not-an-ip")
    valkey.sadd.assert_not_called()


async def test_record_bot_trigger_sets_ttl_on_first_trigger(valkey: AsyncMock) -> None:
    valkey.incr.return_value = 1
    await store.record_bot_trigger(valkey, "1.2.3.4")
    valkey.expire.assert_called_once_with("botcheck:1.2.3.4", 3600)


async def test_record_bot_trigger_does_not_deny_below_threshold(valkey: AsyncMock) -> None:
    valkey.incr.return_value = 2
    await store.record_bot_trigger(valkey, "1.2.3.4")
    valkey.sadd.assert_not_called()


async def test_record_bot_trigger_denies_at_threshold(valkey: AsyncMock) -> None:
    valkey.incr.return_value = 3
    await store.record_bot_trigger(valkey, "1.2.3.4")
    valkey.sadd.assert_called_once_with("denylist:ips", "1.2.3.4")


async def test_record_bot_trigger_ignores_empty_ip(valkey: AsyncMock) -> None:
    await store.record_bot_trigger(valkey, "")
    valkey.incr.assert_not_called()

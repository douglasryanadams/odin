"""Valkey-backed rate limiting counters and search history."""

import datetime
import hashlib
import json
from typing import Any

from valkey.asyncio import Valkey

_ANON_HISTORY_MAX = 10
_ANON_HISTORY_TTL = 7 * 24 * 60 * 60  # 7 days in seconds
_USER_HISTORY_MAX = 50
_USER_HISTORY_TTL = 90 * 24 * 60 * 60  # 90 days in seconds


def _today_utc() -> str:
    return datetime.datetime.now(datetime.UTC).date().isoformat()


def _end_of_day_utc() -> int:
    now = datetime.datetime.now(datetime.UTC)
    tomorrow = (now + datetime.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return int(tomorrow.timestamp())


def _hash_email(email: str) -> str:
    return hashlib.sha256(email.lower().encode()).hexdigest()[:16]


async def consume_magic_jti(client: Valkey, jti: str, exp_ts: int) -> bool:
    """Atomically claim a magic-link nonce; return False if already consumed."""
    key = f"magic:used:{jti}"
    return bool(await client.set(key, "1", nx=True, exat=exp_ts))


_LINK_RATE_TTL = 3600  # 1 hour
_LINK_RATE_EMAIL_CAP = 1
_LINK_RATE_IP_CAP = 5


async def claim_email_link_send(client: Valkey, email: str, ip_address: str) -> bool:
    """Increment per-email and per-IP magic-link counters; return False if either is over its cap.

    Both counters always increment, so a flooder stays locked out for the full hour window.
    """
    email_key = f"linkrate:email:{_hash_email(email)}"
    email_count = await client.incr(email_key)
    if email_count == 1:
        await client.expire(email_key, _LINK_RATE_TTL)
    ip_count = 0
    if ip_address:
        ip_key = f"linkrate:ip:{ip_address}"
        ip_count = await client.incr(ip_key)
        if ip_count == 1:
            await client.expire(ip_key, _LINK_RATE_TTL)
    return email_count <= _LINK_RATE_EMAIL_CAP and ip_count <= _LINK_RATE_IP_CAP


async def get_query_count(client: Valkey, key: str) -> int:
    """Return the current value at key as an int (0 if unset)."""
    val = await client.get(key)
    return int(val) if val else 0


async def get_daily_count(
    client: Valkey,
    *,
    user_email: str | None,
    cookie_id: str,
    ip_address: str,
) -> int:
    """Return today's query count for the requester."""
    today = _today_utc()
    if user_email:
        return await get_query_count(client, f"rate:user:{_hash_email(user_email)}:{today}")
    cookie_count = await get_query_count(client, f"rate:anon:{cookie_id}:{today}")
    ip_count = await get_query_count(client, f"rate:anon:{ip_address}:{today}")
    return max(cookie_count, ip_count)


async def record_query(
    client: Valkey, *, user_email: str | None, cookie_id: str, ip_address: str
) -> None:
    """Increment today's query counters for the requester."""
    eod = _end_of_day_utc()
    today = _today_utc()
    if user_email:
        key = f"rate:user:{_hash_email(user_email)}:{today}"
        await client.incr(key)
        await client.expireat(key, eod)
    else:
        for key in (f"rate:anon:{cookie_id}:{today}", f"rate:anon:{ip_address}:{today}"):
            await client.incr(key)
            await client.expireat(key, eod)


async def is_rate_limited(  # noqa: PLR0913
    client: Valkey,
    *,
    user_email: str | None,
    cookie_id: str,
    ip_address: str,
    anon_limit: int,
    auth_limit: int,
) -> bool:
    """Return True if the requester has reached their daily quota."""
    today = _today_utc()
    if user_email:
        count = await get_query_count(client, f"rate:user:{_hash_email(user_email)}:{today}")
        return count >= auth_limit
    cookie_count = await get_query_count(client, f"rate:anon:{cookie_id}:{today}")
    ip_count = await get_query_count(client, f"rate:anon:{ip_address}:{today}")
    return max(cookie_count, ip_count) >= anon_limit


async def push_history(
    client: Valkey,
    *,
    user_email: str | None,
    cookie_id: str,
    ip_address: str,
    entry: dict[str, str],
) -> None:
    """Prepend an entry to the requester's search history, capped to max depth.

    Anonymous history is written under both cookie and IP keys so that either
    identifier alone is sufficient to surface prior history on the next visit.
    """
    raw = json.dumps(entry)
    if user_email:
        key = f"history:user:{_hash_email(user_email)}"
        await client.lpush(key, raw)
        await client.ltrim(key, 0, _USER_HISTORY_MAX - 1)
        await client.expire(key, _USER_HISTORY_TTL)
    else:
        for key in (f"history:anon:{cookie_id}", f"history:anon:{ip_address}"):
            await client.lpush(key, raw)
            await client.ltrim(key, 0, _ANON_HISTORY_MAX - 1)
            await client.expire(key, _ANON_HISTORY_TTL)


async def delete_user(client: Valkey, email: str) -> None:
    """Remove all per-user data: history, magic-link rate counter, daily rate counters."""
    user_hash = _hash_email(email)
    keys: list[str] = [f"history:user:{user_hash}", f"linkrate:email:{user_hash}"]
    keys.extend([key.decode() async for key in client.scan_iter(match=f"rate:user:{user_hash}:*")])
    if keys:
        await client.delete(*keys)


async def get_history(
    client: Valkey,
    *,
    user_email: str | None,
    cookie_id: str,
    ip_address: str,
    count: int = 20,
) -> list[dict[str, Any]]:
    """Return the most recent history entries for the requester.

    For anonymous users, merges results from the cookie and IP keys and
    deduplicates by exact entry so a user who changes only one identifier
    still sees their prior history.
    """
    if user_email:
        key = f"history:user:{_hash_email(user_email)}"
        items: list[bytes] = await client.lrange(key, 0, count - 1)
    else:
        cookie_items: list[bytes] = await client.lrange(f"history:anon:{cookie_id}", 0, count - 1)
        ip_items: list[bytes] = await client.lrange(f"history:anon:{ip_address}", 0, count - 1)
        seen: set[bytes] = set()
        items = []
        for raw in cookie_items + ip_items:
            if raw not in seen:
                seen.add(raw)
                items.append(raw)
                if len(items) >= count:
                    break

    result: list[dict[str, Any]] = []
    for raw in items:
        try:
            result.append(json.loads(raw))
        except (json.JSONDecodeError, TypeError):
            continue
    return result

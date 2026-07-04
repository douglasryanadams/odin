"""Valkey-backed rate limiting counters and magic-link nonces."""

import datetime
import ipaddress

from valkey.asyncio import Valkey

from odin.identity import Requester
from odin.identity import hash_email as _hash_email

_DENYLIST_IPS_KEY = "denylist:ips"
_BOT_TRIGGER_TTL = 3600  # 1 hour
_BOT_TRIGGER_THRESHOLD = 3


def _today_utc() -> str:
    return datetime.datetime.now(datetime.UTC).date().isoformat()


def _end_of_day_utc() -> int:
    now = datetime.datetime.now(datetime.UTC)
    tomorrow = (now + datetime.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return int(tomorrow.timestamp())


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


async def get_daily_count(client: Valkey, requester: Requester) -> int:
    """Return today's query count for the requester."""
    today = _today_utc()
    if requester.user_email:
        key = f"rate:user:{_hash_email(requester.user_email)}:{today}"
        return await get_query_count(client, key)
    cookie_count = await get_query_count(client, f"rate:anon:{requester.cookie_id}:{today}")
    ip_count = await get_query_count(client, f"rate:anon:{requester.ip_address}:{today}")
    return max(cookie_count, ip_count)


async def record_query(client: Valkey, requester: Requester) -> None:
    """Increment today's query counters for the requester."""
    eod = _end_of_day_utc()
    today = _today_utc()
    if requester.user_email:
        key = f"rate:user:{_hash_email(requester.user_email)}:{today}"
        await client.incr(key)
        await client.expireat(key, eod)
    else:
        for key in (
            f"rate:anon:{requester.cookie_id}:{today}",
            f"rate:anon:{requester.ip_address}:{today}",
        ):
            await client.incr(key)
            await client.expireat(key, eod)


async def is_rate_limited(
    client: Valkey, requester: Requester, *, anon_limit: int, auth_limit: int
) -> bool:
    """Return True if the requester has reached their daily quota."""
    today = _today_utc()
    if requester.user_email:
        key = f"rate:user:{_hash_email(requester.user_email)}:{today}"
        count = await get_query_count(client, key)
        return count >= auth_limit
    cookie_count = await get_query_count(client, f"rate:anon:{requester.cookie_id}:{today}")
    ip_count = await get_query_count(client, f"rate:anon:{requester.ip_address}:{today}")
    return max(cookie_count, ip_count) >= anon_limit


async def delete_user(client: Valkey, email: str) -> None:
    """Remove the user's ValKey state: magic-link and daily rate-limit counters.

    Durable data (signups, search history) lives in Postgres and is removed
    separately during account deletion.
    """
    user_hash = _hash_email(email)
    keys: list[str] = [f"linkrate:email:{user_hash}"]
    keys.extend([key.decode() async for key in client.scan_iter(match=f"rate:user:{user_hash}:*")])
    if keys:
        await client.delete(*keys)


def _decode(value: str | bytes) -> str:
    return value.decode() if isinstance(value, bytes) else value


async def is_ip_denied(client: Valkey, ip_address: str) -> bool:
    """Return True if ip_address is on the denylist."""
    return bool(await client.sismember(_DENYLIST_IPS_KEY, ip_address))


async def deny_ip(client: Valkey, ip_address: str) -> None:
    """Add an IP address to the denylist. Raises ValueError if it is not a valid address."""
    ipaddress.ip_address(ip_address)
    await client.sadd(_DENYLIST_IPS_KEY, ip_address)


async def allow_ip(client: Valkey, ip_address: str) -> None:
    """Remove an IP address from the denylist."""
    await client.srem(_DENYLIST_IPS_KEY, ip_address)


async def list_denied(client: Valkey) -> list[str]:
    """Return every denied IP address, sorted."""
    ips = await client.smembers(_DENYLIST_IPS_KEY)
    return sorted(_decode(entry) for entry in ips)


async def record_bot_trigger(client: Valkey, ip_address: str) -> None:
    """Count a bot-detection trigger for ip_address; deny it once it crosses the threshold.

    Counts within a rolling hour, mirroring claim_email_link_send's incr-then-expire pattern.
    """
    if not ip_address:
        return
    key = f"botcheck:{ip_address}"
    count = await client.incr(key)
    if count == 1:
        await client.expire(key, _BOT_TRIGGER_TTL)
    if count >= _BOT_TRIGGER_THRESHOLD:
        await deny_ip(client, ip_address)

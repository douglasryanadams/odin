"""Profile result cache keyed by normalized query."""

import hashlib
import json
import re
from typing import Any, cast

from valkey.asyncio import Valkey

_PREFIX = "cache:profile"
_TTL_SECONDS = 24 * 60 * 60

_WHITESPACE = re.compile(r"\s+")


def normalize(query: str) -> str:
    """Lowercase, strip, and collapse internal whitespace."""
    return _WHITESPACE.sub(" ", query.strip().lower())


def _key(query: str) -> str:
    return f"{_PREFIX}:{hashlib.sha256(normalize(query).encode()).hexdigest()}"


async def get(client: Valkey, query: str) -> list[dict[str, Any]] | None:
    """Return cached events for a query, or None if not cached."""
    raw = await client.get(_key(query))
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, list):
        return None
    return [
        cast("dict[str, Any]", item) for item in cast("list[Any]", data) if isinstance(item, dict)
    ]


async def put(client: Valkey, query: str, events: list[dict[str, Any]]) -> None:
    """Store the event sequence for a query with the cache TTL."""
    await client.set(_key(query), json.dumps(events), ex=_TTL_SECONDS)

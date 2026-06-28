"""Profile result cache keyed by normalized query."""

import hashlib
import json
import re
import unicodedata
from typing import Any, cast

from valkey.asyncio import Valkey

_PREFIX = "cache:profile:v4"
_TTL_SECONDS = 24 * 60 * 60

_WHITESPACE = re.compile(r"\s+")
_PUNCTUATION_AS_SPACE = re.compile(r"[-_.]")
# Matches ASCII apostrophe, curly single quotes, and modifier-letter apostrophe.
_APOSTROPHE_VARIANTS = re.compile("[\x27\u2018\u2019\u02bc]")
# Matches a trailing possessive: apostrophe (any variant) followed by 's'.
_POSSESSIVE = re.compile("[\x27\u2018\u2019\u02bc]s$", re.IGNORECASE)


def normalize(query: str) -> str:
    """Normalize a query for cache-key derivation.

    Folds Unicode compatibility forms (NFKC), strips diacritics, collapses
    punctuation separators (hyphens, underscores, periods) to spaces, strips
    possessives, lowercases, and collapses whitespace. Does not attempt
    typo correction or alias resolution — those carry wrong-entity risk.
    """
    # NFKC first to unify compatibility forms (e.g. fullwidth characters).
    text = unicodedata.normalize("NFKC", query)
    # Strip trailing possessive before any other transforms.
    text = _POSSESSIVE.sub("", text.strip())
    # NFKD then drop combining marks (category Mn) for diacritic folding.
    text = "".join(
        c for c in unicodedata.normalize("NFKD", text) if unicodedata.category(c) != "Mn"
    )
    # Replace punctuation separators with spaces so "brian-warner" == "brian warner".
    text = _PUNCTUATION_AS_SPACE.sub(" ", text)
    # Remove remaining apostrophe variants (e.g. in contractions that survive).
    text = _APOSTROPHE_VARIANTS.sub("", text)
    return _WHITESPACE.sub(" ", text.strip().lower())


def _key(query: str, mode: str) -> str:
    return f"{_PREFIX}:{mode}:{hashlib.sha256(normalize(query).encode()).hexdigest()}"


async def get(client: Valkey, query: str, mode: str) -> list[dict[str, Any]] | None:
    """Return cached events for a query in the given mode, or None if not cached.

    `mode` ("fast" or "deep") is folded into the key so a deep result is
    never served to a fast request or vice versa — the two pipelines produce
    different event sequences for the same query.
    """
    raw = await client.get(_key(query, mode))
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


async def put(client: Valkey, query: str, mode: str, events: list[dict[str, Any]]) -> None:
    """Store the event sequence for a query and mode with the cache TTL."""
    await client.set(_key(query, mode), json.dumps(events), ex=_TTL_SECONDS)

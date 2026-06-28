"""Tests for the profile result cache: normalization, key derivation, and storage."""

import json
from unittest.mock import AsyncMock

import pytest

from odin import cache

_EVENTS = [{"type": "categorized", "category": "person"}, {"type": "done"}]


@pytest.fixture
def valkey() -> AsyncMock:
    client = AsyncMock()
    client.get.return_value = None
    return client


@pytest.mark.parametrize(
    ("raw", "normalized"),
    [
        ("Marie Curie", "marie curie"),
        ("  Marie Curie  ", "marie curie"),
        ("MARIE\tCURIE", "marie curie"),
        ("marie   curie", "marie curie"),
        ("marie\ncurie", "marie curie"),
        # Diacritic folding: accented characters collapse to ASCII equivalents.
        ("Brían Wärner", "brian warner"),
        ("MARÍE  CURIE", "marie curie"),
        # Punctuation/hyphen folding: separators become spaces.
        ("brian-warner", "brian warner"),
        ("brian_warner", "brian warner"),
        # Possessive folding: trailing straight and curly apostrophe possessives are stripped.
        ("Brian Warner's", "brian warner"),
        ("Brian Warner\u2019s", "brian warner"),
    ],
)
def test_normalize_collapses_case_whitespace_and_internal_runs(raw: str, normalized: str) -> None:
    """normalize() folds case, trims, and collapses internal whitespace runs to one space."""
    assert cache.normalize(raw) == normalized


def test_normalize_does_not_merge_distinct_entities() -> None:
    """Distinct entities must not collide after normalization."""
    assert cache.normalize("brian warner") != cache.normalize("marilyn manson")
    assert cache.normalize("marie curie") != cache.normalize("pierre curie")


def test_queries_that_normalize_alike_share_a_cache_key() -> None:
    """Two queries differing only in case or whitespace must hash to the same cache key.

    This is the property that makes the cache useful: a user who searches
    "Marie Curie" and another who searches "  marie   curie  " should hit the
    same entry. _key derives entirely from normalize(), so this also pins that
    the two functions stay coupled the way the cache depends on.
    """
    assert cache._key("Marie Curie", "fast") == cache._key("  marie   curie  ", "fast")  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]


def test_queries_that_normalize_differently_use_different_keys() -> None:
    """Distinct normalized queries must not collide on the same cache key."""
    assert cache._key("Marie Curie", "fast") != cache._key("Pierre Curie", "fast")  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]


def test_fast_and_deep_modes_use_different_keys_for_the_same_query() -> None:
    """The same query in fast and deep mode must not collide on one cache entry.

    The two pipelines emit different event sequences for the same subject —
    serving one mode's cached result to the other's request would be wrong.
    """
    assert cache._key("Marie Curie", "fast") != cache._key("Marie Curie", "deep")  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]


@pytest.mark.asyncio
async def test_get_returns_none_on_a_cache_miss(valkey: AsyncMock) -> None:
    """A missing key (Valkey returns falsy) is reported as no cached entry."""
    valkey.get.return_value = None
    assert await cache.get(valkey, "marie curie", "fast") is None


@pytest.mark.asyncio
async def test_get_returns_none_for_malformed_json(valkey: AsyncMock) -> None:
    """Corrupted payloads degrade to a cache miss rather than raising."""
    valkey.get.return_value = b"not json"
    assert await cache.get(valkey, "marie curie", "fast") is None


@pytest.mark.asyncio
async def test_get_returns_none_when_payload_is_not_a_list(valkey: AsyncMock) -> None:
    """A well-formed JSON payload of the wrong shape (not a list) is treated as a miss."""
    valkey.get.return_value = json.dumps({"not": "a list"}).encode()
    assert await cache.get(valkey, "marie curie", "fast") is None


@pytest.mark.asyncio
async def test_get_filters_out_non_dict_items(valkey: AsyncMock) -> None:
    """Non-dict entries in an otherwise valid list are dropped, not surfaced or raised."""
    valkey.get.return_value = json.dumps([{"type": "done"}, "garbage", 42, None]).encode()

    result = await cache.get(valkey, "marie curie", "fast")

    assert result == [{"type": "done"}]


@pytest.mark.asyncio
async def test_get_returns_the_decoded_event_list_on_a_hit(valkey: AsyncMock) -> None:
    """A well-formed cache hit round-trips the stored events unchanged."""
    valkey.get.return_value = json.dumps(_EVENTS).encode()
    assert await cache.get(valkey, "marie curie", "fast") == _EVENTS


@pytest.mark.asyncio
async def test_put_stores_events_under_the_key_get_will_look_up(valkey: AsyncMock) -> None:
    """put() writes to the same key normalize/_key derive, with the documented TTL."""
    await cache.put(valkey, "Marie Curie", "fast", _EVENTS)

    valkey.set.assert_awaited_once()
    (key, payload), kwargs = valkey.set.call_args
    assert key == cache._key("marie curie", "fast")  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
    assert json.loads(payload) == _EVENTS
    assert kwargs == {"ex": cache._TTL_SECONDS}  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]

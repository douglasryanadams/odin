"""Integration test fixtures."""

from collections.abc import AsyncIterator

import pytest
from valkey.asyncio import Valkey

from odin.config import settings


@pytest.fixture(autouse=True)
async def _flush_odin_valkey() -> AsyncIterator[None]:  # pyright: ignore[reportUnusedFunction]
    """Reset odin-valkey before each integration test.

    Rate-limit counters and cached profiles persist across `make test-integration`
    runs. Without this, the anonymous daily quota trips after a few sessions and
    every request returns only a `rate_limited` event.
    """
    client: Valkey = Valkey.from_url(settings.odin_valkey_url)
    try:
        await client.flushdb()
        yield
    finally:
        await client.aclose()

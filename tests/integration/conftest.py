"""Integration test fixtures."""

import os
from collections.abc import AsyncIterator

import asyncpg
import pytest
from alembic.config import Config
from valkey.asyncio import Valkey

from alembic import command
from odin import db
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


@pytest.fixture(scope="session", autouse=True)
def _migrate_test_db() -> None:  # pyright: ignore[reportUnusedFunction]
    """Bring the integration database schema up to head once per session."""
    command.upgrade(Config("alembic.ini"), "head")


@pytest.fixture
async def db_pool() -> AsyncIterator[asyncpg.Pool]:
    """Yield a least-privilege (odin_app) pool against a freshly truncated schema.

    Truncation runs over a separate owner connection because TRUNCATE is not
    granted to the runtime role by design. The yielded pool connects as odin_app,
    so the tests exercise the same privilege boundary the app runs under.
    """
    owner = await asyncpg.connect(os.environ["DATABASE_MIGRATION_URL"])
    try:
        await owner.execute("TRUNCATE signups, search_history RESTART IDENTITY CASCADE")
    finally:
        await owner.close()

    pool = await db.create_pool(settings.database_url)
    try:
        yield pool
    finally:
        await pool.close()

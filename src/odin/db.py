"""asyncpg connection pool: lifespan management and the request-scoped dependency.

Runtime database access uses asyncpg directly with hand-written SQL. Alembic owns
schema migrations and is the only place SQLAlchemy is imported; it never enters
this request path.
"""

import asyncpg
from fastapi import Request

# Sized for a low-traffic app sharing a small host with the web workers, Chromium,
# nginx and Valkey. Keep this small; a large pool on a 1-2 GiB box is wasteful.
_MIN_POOL_SIZE = 1
_MAX_POOL_SIZE = 5


async def create_pool(dsn: str) -> asyncpg.Pool:
    """Open the shared asyncpg pool for the given DSN."""
    return await asyncpg.create_pool(dsn, min_size=_MIN_POOL_SIZE, max_size=_MAX_POOL_SIZE)


def get_db_pool(request: Request) -> asyncpg.Pool:
    """Return the shared asyncpg pool from app state."""
    return request.app.state.db_pool  # type: ignore[no-any-return]

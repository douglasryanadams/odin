"""Alembic migration environment.

Migrations run as the owner/migrator role, which is separate from the
least-privilege role the application uses at runtime. The owner DSN comes from
DATABASE_MIGRATION_URL, not from the app's settings.database_url, so the running
app never holds credentials that can reshape the schema. The DSN is a plain
``postgresql://`` URL; SQLAlchemy's async engine needs the
``postgresql+asyncpg://`` dialect form, so we rewrite the scheme here.

Migrations are hand-written (no autogenerate), so ``target_metadata`` is None.
"""

import asyncio
import os
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

_migration_url = os.environ.get("DATABASE_MIGRATION_URL")
if not _migration_url:
    message = (
        "DATABASE_MIGRATION_URL is not set. Migrations must run as the owner role, "
        "not the least-privilege application role. Set DATABASE_MIGRATION_URL to the "
        "owner DSN (e.g. postgresql://odin:PASSWORD@odin-postgres:5432/odin)."
    )
    raise RuntimeError(message)

_async_url = _migration_url.replace("postgresql://", "postgresql+asyncpg://", 1)
config.set_main_option("sqlalchemy.url", _async_url)

target_metadata = None


def _do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def _run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(_do_run_migrations)
    await connectable.dispose()


def run_migrations_offline() -> None:
    """Emit SQL to stdout without a live connection."""
    context.configure(url=_async_url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live async connection."""
    asyncio.run(_run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

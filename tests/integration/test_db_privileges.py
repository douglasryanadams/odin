"""The runtime role must be least-privilege: DML yes, DDL and superuser no.

Migrations run as the owner role (odin); the app connects as odin_app. This test
pins that separation against a real Postgres so a regression that handed the app
a privileged DSN, or relaxed the grants, fails the build.

The privilege boundary is asserted through the catalog (has_*_privilege, pg_roles)
rather than by attempting forbidden DDL: a denied CREATE/DROP emits a server-side
ERROR that the integration harness's log scan would flag as a failure.
"""

import asyncpg
import pytest

pytestmark = pytest.mark.integration


async def test_app_role_is_least_privilege(db_pool: asyncpg.Pool) -> None:
    assert await db_pool.fetchval("SELECT current_user") == "odin_app"

    role = await db_pool.fetchrow(
        "SELECT rolsuper, rolcreatedb, rolcreaterole FROM pg_roles WHERE rolname = current_user"
    )
    assert role["rolsuper"] is False
    assert role["rolcreatedb"] is False
    assert role["rolcreaterole"] is False

    # Can use the schema but not create objects in it: no DDL.
    assert await db_pool.fetchval("SELECT has_schema_privilege('public', 'USAGE')") is True
    assert await db_pool.fetchval("SELECT has_schema_privilege('public', 'CREATE')") is False

    # Holds DML on its tables, but cannot truncate them or own (and thus drop/alter) them.
    for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        assert await db_pool.fetchval("SELECT has_table_privilege('signups', $1)", privilege)
    assert await db_pool.fetchval("SELECT has_table_privilege('signups', 'TRUNCATE')") is False
    assert (
        await db_pool.fetchval("SELECT tableowner FROM pg_tables WHERE tablename = 'signups'")
        == "odin"
    )

    # And DML works in practice through the app's pool.
    await db_pool.execute(
        "INSERT INTO signups (email_hash) VALUES ('privtest') ON CONFLICT DO NOTHING"
    )

#!/bin/sh
# Create the least-privilege runtime role on first initialization of the data
# directory. The bootstrap superuser (POSTGRES_USER, "odin") owns the schema and
# runs Alembic migrations; the application connects as this role instead, so the
# request path cannot create, drop, or alter tables.
#
# Default privileges are set FOR the owner role, so every table and sequence a
# later migration creates is automatically usable by odin_app without a per-
# migration grant. This runs only on a fresh volume; an existing dev volume must
# be recreated (docker compose down -v) to pick up the role.
set -eu

: "${ODIN_APP_DB_PASSWORD:?ODIN_APP_DB_PASSWORD must be set to create the runtime role}"

psql -v ON_ERROR_STOP=1 \
  --username "$POSTGRES_USER" \
  --dbname "$POSTGRES_DB" \
  -v app_pw="$ODIN_APP_DB_PASSWORD" \
  -v owner="$POSTGRES_USER" <<'EOSQL'
CREATE ROLE odin_app LOGIN PASSWORD :'app_pw' NOSUPERUSER NOCREATEDB NOCREATEROLE;

GRANT USAGE ON SCHEMA public TO odin_app;

ALTER DEFAULT PRIVILEGES FOR ROLE :"owner" IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO odin_app;

ALTER DEFAULT PRIVILEGES FOR ROLE :"owner" IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO odin_app;
EOSQL

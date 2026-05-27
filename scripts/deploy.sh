#!/bin/bash
set -euo pipefail

: "${AWS_REGION:?AWS_REGION must be set}"
: "${ECR_REGISTRY:?ECR_REGISTRY must be set}"
: "${ECR_REPOSITORY:?ECR_REPOSITORY must be set}"
SECRET_ID="${ODIN_SECRET_ID:-odin/app}"

cd "$(dirname "$0")/.."

aws ecr get-login-password --region "$AWS_REGION" \
  | docker login --username AWS --password-stdin "$ECR_REGISTRY"

docker pull "$ECR_REGISTRY/$ECR_REPOSITORY:latest"
docker tag "$ECR_REGISTRY/$ECR_REPOSITORY:latest" odin-prod

SECRETS_JSON=$(aws secretsmanager get-secret-value \
  --region "$AWS_REGION" \
  --secret-id "$SECRET_ID" \
  --query SecretString \
  --output text)

umask 077
jq -r '
  to_entries
  | map("\(.key | ascii_upcase)=\(.value)")
  | .[]
' <<<"$SECRETS_JSON" > .env
chown ec2-user:ec2-user .env

unset SECRETS_JSON

# Fail fast and clearly if either database password is missing from the secret;
# compose would otherwise abort with an opaque interpolation error.
# POSTGRES_PASSWORD is the owner/migrator role; ODIN_APP_DB_PASSWORD is the
# least-privilege runtime role.
for db_pw_var in POSTGRES_PASSWORD ODIN_APP_DB_PASSWORD; do
  if ! grep -qE "^${db_pw_var}=.+" .env; then
    echo "ERROR: $db_pw_var is missing from the $SECRET_ID secret; add it before deploying." >&2
    exit 1
  fi
done

COMPOSE=(docker compose
  --project-directory .
  -f compose/docker-compose.yml
  -f compose/docker-compose.prod.yml
  -f compose/docker-compose.awslogs.yml)

# Bring the database up and apply migrations with the new image before the app
# serves the new code. Migrations run as the owner role via DATABASE_MIGRATION_URL,
# injected into this one-off container only so the long-lived web service never
# holds credentials that can reshape the schema.
owner_password=$(sed -n 's/^POSTGRES_PASSWORD=//p' .env | head -n1)
"${COMPOSE[@]}" up -d --wait odin-postgres
"${COMPOSE[@]}" run --rm \
  -e DATABASE_MIGRATION_URL="postgresql://odin:${owner_password}@odin-postgres:5432/odin" \
  web alembic upgrade head

"${COMPOSE[@]}" up -d --pull always --force-recreate --wait

docker image prune -af

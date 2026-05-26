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

# Fail fast and clearly if the durable-store password is missing from the secret;
# compose would otherwise abort with an opaque interpolation error.
if ! grep -qE '^POSTGRES_PASSWORD=.+' .env; then
  echo "ERROR: POSTGRES_PASSWORD is missing from the $SECRET_ID secret; add it before deploying." >&2
  exit 1
fi

COMPOSE=(docker compose
  --project-directory .
  -f compose/docker-compose.yml
  -f compose/docker-compose.prod.yml
  -f compose/docker-compose.awslogs.yml)

# Bring the database up and apply migrations with the new image before the app
# serves the new code.
"${COMPOSE[@]}" up -d --wait odin-postgres
"${COMPOSE[@]}" run --rm web alembic upgrade head

"${COMPOSE[@]}" up -d --pull always --force-recreate --wait

docker image prune -af

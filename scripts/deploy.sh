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

docker compose \
  --project-directory . \
  -f compose/docker-compose.yml \
  -f compose/docker-compose.prod.yml \
  -f compose/docker-compose.awslogs.yml \
  up -d --no-deps web

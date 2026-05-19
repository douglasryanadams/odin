#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

COMPOSE=(docker compose --project-directory . -f compose/docker-compose.yml -f compose/docker-compose.prod.yml)

export SECRET_KEY=${SECRET_KEY:-smoke-test-only-dummy-secret-key-32chars}
export APP_URL=${APP_URL:-http://localhost:8000}
export ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY:-smoke-dummy}
export SEARXNG_SECRET=${SEARXNG_SECRET:-smoke-dummy}
export BRAVE_API_KEY=${BRAVE_API_KEY:-smoke-dummy}

teardown() {
  "${COMPOSE[@]}" down --remove-orphans >/dev/null 2>&1 || true
}
trap teardown EXIT

"${COMPOSE[@]}" build web
"${COMPOSE[@]}" up -d --wait

fail() { echo "FAIL: $*" >&2; exit 1; }

BASE=http://localhost:8000

curl -sf "$BASE/health" | grep -q '"ok"' || fail "/health did not return ok"

HEADERS=$(curl -sI "$BASE/static/css/odin.css")
echo "$HEADERS" | grep -qE '^HTTP/1\.[01] 200' || fail "/static/css/odin.css not 200: $HEADERS"
echo "$HEADERS" | grep -qi 'content-type: text/css' || fail "/static/css/odin.css missing text/css: $HEADERS"
echo "$HEADERS" | grep -qi 'cache-control: public, max-age=86400' || fail "/static/css/odin.css missing expected Cache-Control: $HEADERS"
echo "$HEADERS" | grep -qi 'server: nginx' || fail "/static/css/odin.css not served by nginx: $HEADERS"

HEADERS=$(curl -sI "$BASE/favicon.ico")
echo "$HEADERS" | grep -qE '^HTTP/1\.[01] 200' || fail "/favicon.ico not 200: $HEADERS"
echo "$HEADERS" | grep -qi 'content-type: image/' || fail "/favicon.ico wrong content-type: $HEADERS"

curl -sf "$BASE/robots.txt" | grep -q '^User-agent:' || fail "/robots.txt missing User-agent line"

if "${COMPOSE[@]}" logs web 2>/dev/null | grep -E 'GET /static/|GET /favicon\.ico|GET /robots\.txt'; then
  fail "gunicorn served a static or well-known path; Nginx interception is broken"
fi

SSE=$(curl -sN --max-time 2 -o /dev/null -D - "$BASE/profile/stream?q=smoketest" 2>&1 || true)
echo "$SSE" | grep -qi 'content-type: text/event-stream' || fail "SSE wrong content-type: $SSE"
echo "$SSE" | grep -qi 'transfer-encoding: chunked' || fail "SSE not chunked (Nginx is buffering): $SSE"
if echo "$SSE" | grep -qi '^content-length:'; then
  fail "SSE has Content-Length set (Nginx buffered the stream): $SSE"
fi

echo "smoke: all assertions passed"

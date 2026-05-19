#!/bin/sh
# Render settings.yml.tmpl with BRAVE_API_KEY substituted into a tmpfs-backed
# file that lives only in container memory. We point SearXNG at it by setting
# __SEARXNG_SETTINGS_PATH before execing the upstream entrypoint. The rendered
# file is chmod 0400, owned by searxng:searxng, so the key never touches the
# host filesystem and is unreadable to non-root processes inside the container.
set -eu

: "${BRAVE_API_KEY:?BRAVE_API_KEY must be set so the braveapi engine can authenticate}"

SETTINGS_DIR=/run/searxng
SETTINGS_FILE="$SETTINGS_DIR/settings.yml"

mkdir -p "$SETTINGS_DIR"
chown searxng:searxng "$SETTINGS_DIR"
chmod 0700 "$SETTINGS_DIR"

python3 - <<'PY'
import os
from pathlib import Path
from string import Template

template = Path("/etc/searxng/settings.yml.tmpl").read_text()
rendered = Template(template).substitute(BRAVE_API_KEY=os.environ["BRAVE_API_KEY"])
Path("/run/searxng/settings.yml").write_text(rendered)
PY

chown searxng:searxng "$SETTINGS_FILE"
chmod 0400 "$SETTINGS_FILE"

export __SEARXNG_SETTINGS_PATH="$SETTINGS_FILE"

exec /usr/local/searxng/entrypoint.sh "$@"

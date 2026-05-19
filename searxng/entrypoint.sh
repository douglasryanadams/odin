#!/bin/sh
# Render settings.yml.tmpl into settings.yml with BRAVE_API_KEY substituted,
# then hand off to the image's own entrypoint. The image runs as root before
# dropping privileges, so writing into the bind-mounted /etc/searxng/ is fine.
set -eu

: "${BRAVE_API_KEY:?BRAVE_API_KEY must be set so the braveapi engine can authenticate}"

python3 - <<'PY'
import os
from pathlib import Path
from string import Template

template = Path("/etc/searxng/settings.yml.tmpl").read_text()
rendered = Template(template).substitute(BRAVE_API_KEY=os.environ["BRAVE_API_KEY"])
Path("/etc/searxng/settings.yml").write_text(rendered)
PY

exec /usr/local/searxng/entrypoint.sh "$@"

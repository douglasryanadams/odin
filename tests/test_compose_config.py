"""Regression checks for docker-compose configuration."""

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_prod_compose_surfaces_smtp_settings() -> None:
    """The prod compose file must pass every SMTP setting from the secret into the web container.

    The AWS Secrets Manager secret `odin/app` defines smtp_host, smtp_from, smtp_user,
    and smtp_pass; deploy.sh writes them to .env on the host. None of them reach the
    container unless docker-compose.prod.yml lists them in web.environment, because
    Compose's automatic .env loading only handles ${VAR} substitution in the YAML.
    Without this passthrough, send_magic_link silently falls back to dev mode (or sends
    with the wrong From address if config.py defaults drift from operator intent).
    """
    data = yaml.safe_load((REPO_ROOT / "docker-compose.prod.yml").read_text())
    env = data["services"]["web"]["environment"]
    names = {entry.split("=", 1)[0] for entry in env}
    missing = {"SMTP_HOST", "SMTP_FROM", "SMTP_USER", "SMTP_PASS"} - names
    assert not missing, f"docker-compose.prod.yml web.environment missing: {sorted(missing)}"

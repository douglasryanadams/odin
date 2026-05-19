"""Regression checks for docker-compose configuration."""

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_prod_compose_surfaces_smtp_settings() -> None:
    """The prod compose file must pass every SMTP setting from the secret into the web container.

    The AWS Secrets Manager secret `odin/app` defines smtp_host, smtp_from, smtp_user,
    and smtp_pass; deploy.sh writes them to .env on the host. None of them reach the
    container unless compose/docker-compose.prod.yml lists them in web.environment,
    because Compose's automatic .env loading only handles ${VAR} substitution in the
    YAML. Without this passthrough, send_magic_link silently falls back to dev mode
    (or sends with the wrong From address if config.py defaults drift from operator
    intent).
    """
    data = yaml.safe_load((REPO_ROOT / "compose" / "docker-compose.prod.yml").read_text())
    env = data["services"]["web"]["environment"]
    names = {entry.split("=", 1)[0] for entry in env}
    missing = {"SMTP_HOST", "SMTP_FROM", "SMTP_USER", "SMTP_PASS"} - names
    assert not missing, (
        f"compose/docker-compose.prod.yml web.environment missing: {sorted(missing)}"
    )


def test_searxng_service_passes_brave_api_key_in_both_compose_files() -> None:
    """SearXNG's braveapi engine requires BRAVE_API_KEY at container start.

    The base docker-compose.yml overrides the SearXNG entrypoint to render
    settings.yml from a template that contains `${BRAVE_API_KEY}`; the prod
    file ships the same env passthrough so the EC2 host's .env reaches the
    container. If either file is missing the entry, the entrypoint exits 1
    with the `BRAVE_API_KEY must be set` message before SearXNG starts.
    """
    for compose_file in ("docker-compose.yml", "docker-compose.prod.yml"):
        data = yaml.safe_load((REPO_ROOT / "compose" / compose_file).read_text())
        env = data["services"]["searxng"]["environment"]
        names = {entry.split("=", 1)[0] for entry in env}
        assert "BRAVE_API_KEY" in names, (
            f"compose/{compose_file} searxng.environment is missing BRAVE_API_KEY"
        )


def test_searxng_service_uses_template_entrypoint() -> None:
    """SearXNG's container must run our entrypoint so the template is rendered."""
    data = yaml.safe_load((REPO_ROOT / "compose" / "docker-compose.yml").read_text())
    entrypoint = data["services"]["searxng"]["entrypoint"]
    assert "/etc/searxng/entrypoint.sh" in entrypoint, (
        f"searxng entrypoint must invoke /etc/searxng/entrypoint.sh, got {entrypoint!r}"
    )

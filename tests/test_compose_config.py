"""Regression checks for docker-compose configuration."""

import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]


def _service_env_names(*compose_filenames: str) -> set[str]:
    """Return the union of environment-variable names declared across services in
    the named compose files. Both `VAR=value` and bare `VAR` (compose interpolation
    from .env / shell) are recognised."""
    names: set[str] = set()
    for filename in compose_filenames:
        data = yaml.safe_load((REPO_ROOT / "compose" / filename).read_text())
        for service in (data.get("services") or {}).values():
            for entry in service.get("environment") or []:
                names.add(entry.split("=", 1)[0])
    return names


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


def test_searxng_renders_settings_into_tmpfs() -> None:
    """The rendered settings.yml (which contains the substituted BRAVE_API_KEY)
    must live on an in-container tmpfs, not the host bind mount, so the key
    never reaches the host filesystem."""
    data = yaml.safe_load((REPO_ROOT / "compose" / "docker-compose.yml").read_text())
    tmpfs = data["services"]["searxng"].get("tmpfs") or []
    assert any(entry.startswith("/run/searxng") for entry in tmpfs), (
        f"searxng service must mount a tmpfs at /run/searxng so the rendered "
        f"settings.yml (with BRAVE_API_KEY) does not touch the host filesystem; "
        f"got tmpfs={tmpfs!r}"
    )


def test_required_env_vars_are_forwarded_through_compose() -> None:
    """Every name in the 'Required' section of config/.env.example must be passed
    through to some service in dev or prod compose. Catches the case where a new
    required env var is added but the compose passthrough is missed - Compose's
    automatic .env loading only handles ${VAR} substitution in the YAML, it does
    not pass shell/.env values to containers unless the service lists the name
    under environment:.
    """
    env_example = (REPO_ROOT / "config" / ".env.example").read_text()
    required_block = re.search(
        r"^# Required\n(.*?)\n^#", env_example, re.DOTALL | re.MULTILINE
    )
    assert required_block, "could not locate '# Required' section in config/.env.example"
    required_vars = {
        line.split("=", 1)[0].strip()
        for line in required_block.group(1).splitlines()
        if line and not line.lstrip().startswith("#")
    }
    forwarded = _service_env_names("docker-compose.yml", "docker-compose.prod.yml")
    missing = required_vars - forwarded
    assert not missing, (
        f"config/.env.example marks {sorted(missing)} as required, but "
        f"compose/docker-compose.yml and compose/docker-compose.prod.yml do not "
        f"forward them to any service. Add each to the relevant service's "
        f"`environment:` list (bare name, no `=`) so .env / host values reach the container."
    )

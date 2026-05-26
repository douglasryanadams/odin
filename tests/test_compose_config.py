"""Regression checks for docker-compose configuration."""

import re
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_compose(filename: str) -> Any:  # noqa: ANN401  # yaml.safe_load is untyped
    return yaml.safe_load((REPO_ROOT / "compose" / filename).read_text())


def _service_env_names(*compose_filenames: str) -> set[str]:
    """Return env-var names declared across services in the named compose files.

    Both `VAR=value` and bare `VAR` (compose interpolation from .env / shell)
    are recognised.
    """
    names: set[str] = set()
    for filename in compose_filenames:
        services = _load_compose(filename)["services"]
        for service_name in services:
            entries = services[service_name].get("environment")
            if not entries:
                continue
            for entry in entries:
                names.add(str(entry).split("=", 1)[0])
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


def test_web_service_passes_brave_api_key_in_both_compose_files() -> None:
    """The web service's direct Brave backend reads BRAVE_API_KEY from the container env.

    Compose's automatic .env loading only handles ${VAR} substitution in the YAML;
    it does not pass shell/.env values into a container unless the service lists the
    name under environment:. Both the base and prod compose files must forward
    BRAVE_API_KEY to web, or BraveBackend never instantiates (it fails closed without
    the key).
    """
    for compose_file in ("docker-compose.yml", "docker-compose.prod.yml"):
        data = yaml.safe_load((REPO_ROOT / "compose" / compose_file).read_text())
        env = data["services"]["web"]["environment"]
        names = {entry.split("=", 1)[0] for entry in env}
        assert "BRAVE_API_KEY" in names, (
            f"compose/{compose_file} web.environment is missing BRAVE_API_KEY"
        )


def test_postgres_service_persists_data_and_reports_health() -> None:
    """The durable store must survive container recreation and signal readiness.

    signups and search_history live in odin-postgres. Without a named volume the
    data is lost on every recreate (deploy.sh runs --force-recreate); without a
    healthcheck the web container can race ahead and fail its first queries
    against a Postgres still in crash recovery.
    """
    data = _load_compose("docker-compose.yml")
    postgres = data["services"]["odin-postgres"]

    mounts = postgres.get("volumes", [])
    data_mounts = [m for m in mounts if m.endswith(":/var/lib/postgresql/data")]
    assert data_mounts, "odin-postgres must mount a named volume at /var/lib/postgresql/data"
    volume_name = data_mounts[0].split(":", 1)[0]
    assert volume_name in data.get("volumes", {}), (
        f"named volume {volume_name!r} must be declared under top-level volumes:"
    )

    test_cmd = " ".join(postgres.get("healthcheck", {}).get("test", []))
    assert "pg_isready" in test_cmd, "odin-postgres healthcheck should use pg_isready"


def test_prod_postgres_password_is_required_with_no_repo_default() -> None:
    """Prod must fail hard rather than fall back to a password baked into the repo.

    The base compose carries a convenience default (POSTGRES_PASSWORD:-odin) for
    local dev and CI. The prod overlay must override it with the required form
    (:?), so an unset or empty value aborts `docker compose` and the stack never
    starts. A regression that reintroduced a :- fallback here would silently run
    production on a password from the repository.
    """
    env = _load_compose("docker-compose.prod.yml")["services"]["odin-postgres"]["environment"]
    entries = [e for e in env if e.startswith("POSTGRES_PASSWORD=")]
    assert entries, "prod compose must pin POSTGRES_PASSWORD on odin-postgres"
    value = entries[0]
    assert ":?" in value, "prod POSTGRES_PASSWORD must use the required (:?) form so it fails hard"
    assert ":-" not in value, "prod POSTGRES_PASSWORD must not carry a default fallback"


def test_web_waits_for_postgres_health() -> None:
    """Web must wait for Postgres health before starting.

    The asyncpg pool opens in the FastAPI lifespan at startup; if Postgres is not
    yet accepting connections the app crashes on boot. A depends_on health
    condition serializes startup.
    """
    web = _load_compose("docker-compose.yml")["services"]["web"]
    condition = web.get("depends_on", {}).get("odin-postgres", {}).get("condition")
    assert condition == "service_healthy", "web must depend_on odin-postgres being healthy"


def test_required_env_vars_are_forwarded_through_compose() -> None:
    """Required env vars from .env.example must reach a container via compose.

    Catches the case where a new required env var is added but the compose
    passthrough is missed - Compose's automatic .env loading only handles
    ${VAR} substitution in the YAML, it does not pass shell/.env values to
    containers unless the service lists the name under environment:.
    """
    env_example = (REPO_ROOT / "config" / ".env.example").read_text()
    required_block = re.search(r"^# Required\n(.*?)\n^#", env_example, re.DOTALL | re.MULTILINE)
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

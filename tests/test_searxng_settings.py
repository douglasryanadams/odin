"""Regression checks for the SearXNG settings template and envsubst rendering."""

from pathlib import Path
from string import Template

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_PATH = REPO_ROOT / "searxng" / "settings.yml.tmpl"


def _render_template(brave_api_key: str) -> dict[str, object]:
    """Substitute the entrypoint's env vars into the template and parse as YAML."""
    rendered = Template(TEMPLATE_PATH.read_text()).substitute(BRAVE_API_KEY=brave_api_key)
    data = yaml.safe_load(rendered)
    assert isinstance(data, dict), "settings.yml.tmpl must render to a YAML mapping"
    return data


def test_braveapi_engine_receives_substituted_api_key() -> None:
    data = _render_template("test-key-123")
    engines = data["engines"]
    braveapi = [e for e in engines if e.get("engine") == "braveapi"]
    assert len(braveapi) == 1, f"expected exactly one braveapi engine, got {len(braveapi)}"
    assert braveapi[0]["api_key"] == "test-key-123"


def test_scraping_brave_engine_is_gone() -> None:
    data = _render_template("unused")
    engines = data["engines"]
    scrapers = [e for e in engines if e.get("engine") == "brave"]
    assert not scrapers, "scraping brave engine must be removed when braveapi is enabled"


def test_failing_scraper_engines_are_pruned() -> None:
    data = _render_template("unused")
    engine_names = {e.get("engine") for e in data["engines"]}
    assert "startpage" not in engine_names
    assert "qwant" not in engine_names
    assert "mojeek" in engine_names, "mojeek must remain as a cooperative independent index"

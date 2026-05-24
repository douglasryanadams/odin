"""Regression checks for the SearXNG settings template and envsubst rendering."""

from pathlib import Path
from string import Template
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_PATH = REPO_ROOT / "searxng" / "settings.yml.tmpl"


def _render_template(brave_api_key: str) -> Any:  # noqa: ANN401  # yaml.safe_load is untyped
    """Substitute the entrypoint's env vars into the template and parse as YAML."""
    rendered = Template(TEMPLATE_PATH.read_text()).substitute(BRAVE_API_KEY=brave_api_key)
    return yaml.safe_load(rendered)


def test_braveapi_engine_receives_substituted_api_key() -> None:
    data = _render_template("test-key-123")
    braveapi = [e for e in data["engines"] if e.get("engine") == "braveapi"]
    assert len(braveapi) == 1, f"expected exactly one braveapi engine, got {len(braveapi)}"
    assert braveapi[0]["api_key"] == "test-key-123"


def test_scraping_brave_engine_is_gone() -> None:
    data = _render_template("unused")
    scrapers = [e for e in data["engines"] if e.get("engine") == "brave"]
    assert not scrapers, "scraping brave engine must be removed when braveapi is enabled"


def test_search_ban_backoff_is_long_enough_to_silence_blocked_scrapers() -> None:
    """Failing engines should back off at least 10 minutes immediately.

    Mojeek and other scraper engines that are blocked from cloud IPs return
    403 on every request. A short initial ban_time_on_fail makes SearXNG
    retry every 10s/20s/40s and floods the logs. We start the suspension
    at 10 minutes and cap at 1 hour so blocked engines fall quiet quickly.
    """
    data = _render_template("unused")
    assert data["search"]["ban_time_on_fail"] >= 600
    assert data["search"]["max_ban_time_on_fail"] >= 3600


def test_known_blocked_scrapers_are_disabled() -> None:
    """Engines that fail from our IPs must be present-but-disabled.

    startpage / qwant / karmasearch return CAPTCHA / access-denied from
    cloud IPs; wikipedia returns HTTP 429 because SearXNG's hardcoded
    `searxng/<version>` User-Agent trips Wikimedia's bot-rate-limit
    (and SearXNG doesn't support per-engine UA override).

    These cannot be removed via `use_default_settings.engines.remove`
    because SearXNG's network config references some of these names as
    network aliases (e.g. dropping `qwant` raises KeyError at SearXNG
    startup), so we override them with `disabled: true` to keep the
    runtime alive while silencing the requests.
    """
    data = _render_template("unused")
    by_engine = {e["engine"]: e for e in data["engines"]}
    for engine in ("startpage", "qwant", "karmasearch", "wikipedia"):
        assert engine in by_engine, f"{engine} must be present in the engine list"
        assert by_engine[engine]["disabled"] is True, f"{engine} must be disabled"
    assert "mojeek" in by_engine, "mojeek must remain as a free secondary source"
    assert by_engine["mojeek"]["disabled"] is False

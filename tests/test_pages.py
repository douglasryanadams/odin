"""Tests for the static-ish pages: home, health, about, privacy, terms, notice dismissal.

Also covers the sitewide SEO surface (canonical, meta description, OG / Twitter
cards, JSON-LD, favicon variants, robots.txt, sitemap.xml, site.webmanifest) and
the response-level security headers attached by the middleware.
"""

import json
import re
from typing import Any, cast
from unittest.mock import MagicMock

import pytest
from conftest import STATIC_DIR, TEST_SECRET
from fastapi.testclient import TestClient

from odin import auth as _auth

_JSON_LD_PATTERN = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.DOTALL)


def _json_ld_blocks(body: str) -> list[dict[str, Any]]:
    """Extract every JSON-LD <script> block from a rendered page."""
    return [json.loads(match) for match in _JSON_LD_PATTERN.findall(body)]


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


def test_health(client: TestClient) -> None:
    """Verify the health endpoint returns 200 with status ok."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# Index route
# ---------------------------------------------------------------------------


def test_index_renders_wordmark_and_form(client: TestClient) -> None:
    """Index renders the Odin wordmark and search form."""
    response = client.get("/")
    assert response.status_code == 200
    assert ">ODIN<" in response.text
    assert 'id="search-form"' in response.text


def test_index_renders_beta_badge(client: TestClient) -> None:
    """Landing page includes a beta badge so users know the product is in beta."""
    response = client.get("/")
    assert response.status_code == 200
    assert "beta-badge" in response.text
    assert ">Beta<" in response.text


def test_index_sets_anon_cookie_on_first_visit(client: TestClient) -> None:
    """Index sets odin_anon cookie when not already present."""
    response = client.get("/", cookies={})
    assert "odin_anon" in response.cookies


def test_index_does_not_overwrite_existing_anon_cookie(client: TestClient) -> None:
    """Index leaves an existing odin_anon cookie unchanged."""
    response = client.get("/", cookies={"odin_anon": "existing-id"})
    assert "odin_anon" not in response.cookies


def test_anon_cookie_lacks_secure_flag_in_dev(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When cookie_secure is False (local dev), Set-Cookie omits Secure."""
    from odin.config import settings  # noqa: PLC0415

    monkeypatch.setattr(settings, "cookie_secure", False)
    response = client.get("/", cookies={})
    set_cookie = response.headers.get("set-cookie", "")
    assert "odin_anon=" in set_cookie
    assert "Secure" not in set_cookie


def test_anon_cookie_has_secure_flag_when_enabled(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When cookie_secure is True, Set-Cookie for odin_anon includes Secure."""
    from odin.config import settings  # noqa: PLC0415

    monkeypatch.setattr(settings, "cookie_secure", True)
    response = client.get("/", cookies={})
    set_cookie = response.headers.get("set-cookie", "")
    assert "odin_anon=" in set_cookie
    assert "Secure" in set_cookie


def test_index_response_has_security_headers(client: TestClient) -> None:
    """All responses carry baseline security headers."""
    response = client.get("/")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert "default-src 'self'" in response.headers["Content-Security-Policy"]


def test_health_response_also_has_security_headers(client: TestClient) -> None:
    """JSON endpoints get the same headers as HTML ones."""
    response = client.get("/health")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert "Content-Security-Policy" in response.headers


def test_hsts_absent_when_cookie_secure_false(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """HSTS is omitted in dev (plain HTTP) so browsers don't pin localhost to HTTPS."""
    from odin.config import settings  # noqa: PLC0415

    monkeypatch.setattr(settings, "cookie_secure", False)
    response = client.get("/")
    assert "Strict-Transport-Security" not in response.headers


def test_hsts_present_when_cookie_secure_true(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """HSTS is set in production where cookie_secure is True."""
    from odin.config import settings  # noqa: PLC0415

    monkeypatch.setattr(settings, "cookie_secure", True)
    response = client.get("/")
    hsts = response.headers["Strict-Transport-Security"]
    assert "max-age=" in hsts
    assert "includeSubDomains" in hsts


def test_csp_allows_required_external_assets(client: TestClient) -> None:
    """CSP must not block the actual fonts and Font Awesome asset hosts in use."""
    response = client.get("/")
    csp = response.headers["Content-Security-Policy"]
    assert "https://fonts.googleapis.com" in csp
    assert "https://fonts.gstatic.com" in csp
    assert "https://cdnjs.cloudflare.com" in csp


def test_index_shows_quota_when_count_is_nonzero(
    client: TestClient, mock_valkey: MagicMock
) -> None:
    """Index renders remaining quota text when the user has made at least one search."""
    mock_valkey.get.return_value = b"1"
    response = client.get("/", cookies={"odin_anon": "existing-id"})
    assert "remaining" in response.text


def test_index_hides_quota_on_first_visit(client: TestClient) -> None:
    """Index shows no quota message when the count is zero (first-time visitor)."""
    response = client.get("/")
    assert "remaining" not in response.text


def test_index_signed_in_links_to_dashboard_without_searches(client: TestClient) -> None:
    """Signed-in users can reach /dashboard from the home page even before their first search."""
    session = _auth.create_session_value("user@example.com", TEST_SECRET)
    response = client.get("/", cookies={"odin_session": session})
    assert response.status_code == 200
    assert 'href="/dashboard"' in response.text


def test_index_anonymous_first_visit_links_to_login(client: TestClient) -> None:
    """Anonymous visitors see a Sign in link on the home page even before their first search."""
    response = client.get("/")
    assert response.status_code == 200
    assert 'href="/login"' in response.text


def test_index_redirects_to_login_when_anon_rate_limited(
    client: TestClient, mock_valkey: MagicMock
) -> None:
    """Anonymous user who has hit their daily limit is redirected to the login page."""
    mock_valkey.get.return_value = b"5"
    response = client.get("/", cookies={"odin_anon": "test-cookie"}, follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/login?reason=limit"


# ---------------------------------------------------------------------------
# Legal pages and shared chrome
# ---------------------------------------------------------------------------


def test_privacy_page_renders(client: TestClient) -> None:
    """GET /privacy returns the privacy policy with key disclosures."""
    response = client.get("/privacy")
    assert response.status_code == 200
    body = response.text
    assert "Privacy" in body
    assert "Anthropic" in body
    assert "SearXNG" in body or "search engines" in body
    assert "odin@odinseye.info" in body


def test_terms_page_renders(client: TestClient) -> None:
    """GET /terms returns the terms of service."""
    response = client.get("/terms")
    assert response.status_code == 200
    body = response.text
    assert "Terms" in body
    assert "odin@odinseye.info" in body


def test_footer_links_to_privacy_and_terms(client: TestClient) -> None:
    """The shared footer exposes privacy and terms links."""
    response = client.get("/")
    assert response.status_code == 200
    assert 'href="/privacy"' in response.text
    assert 'href="/terms"' in response.text


def test_disclosure_banner_shown_on_first_visit(client: TestClient) -> None:
    """Index renders the disclosure banner when odin_seen_notice cookie is absent."""
    response = client.get("/", cookies={})
    assert response.status_code == 200
    assert 'id="disclosure-banner"' in response.text
    assert "Anthropic" in response.text
    assert 'action="/notice/dismiss"' in response.text


def test_disclosure_banner_hidden_when_cookie_set(client: TestClient) -> None:
    """Index omits the banner once the user has dismissed it."""
    response = client.get("/", cookies={"odin_seen_notice": "1"})
    assert response.status_code == 200
    assert 'id="disclosure-banner"' not in response.text


def test_dismiss_notice_sets_cookie_and_redirects(client: TestClient) -> None:
    """POST /notice/dismiss sets the odin_seen_notice cookie and redirects to referer or home."""
    response = client.post("/notice/dismiss", follow_redirects=False)
    assert response.status_code == 303
    set_cookie = response.headers.get("set-cookie", "")
    assert "odin_seen_notice=1" in set_cookie
    assert "Max-Age=" in set_cookie


# ---------------------------------------------------------------------------
# SEO surface: about page, meta tags, JSON-LD, canonical, robots, sitemap
# ---------------------------------------------------------------------------


def test_about_page_renders(client: TestClient) -> None:
    """GET /about renders a single-h1 About page with the wordmark."""
    response = client.get("/about")
    assert response.status_code == 200
    body = response.text
    assert body.count("<h1") == 1
    assert "About Odin" in body
    assert ">ODIN<" in body


def test_about_page_in_footer_nav(client: TestClient) -> None:
    """Home page footer links to /about."""
    response = client.get("/")
    assert response.status_code == 200
    assert 'href="/about"' in response.text


def _assert_common_seo_tags(body: str) -> None:
    assert '<meta name="description"' in body
    assert '<meta property="og:title"' in body
    assert '<meta property="og:description"' in body
    assert '<meta property="og:url"' in body
    assert '<meta property="og:type"' in body
    assert '<meta property="og:site_name"' in body
    assert '<meta property="og:locale"' in body
    assert '<meta name="twitter:card" content="summary"' in body


def test_home_has_meta_description_and_og_tags(client: TestClient) -> None:
    """Home page emits description + the full OG/Twitter tag set."""
    response = client.get("/")
    assert response.status_code == 200
    _assert_common_seo_tags(response.text)


def test_about_has_meta_description_and_og_tags(client: TestClient) -> None:
    """About page emits description + the full OG/Twitter tag set."""
    response = client.get("/about")
    assert response.status_code == 200
    _assert_common_seo_tags(response.text)


def test_privacy_has_meta_description(client: TestClient) -> None:
    response = client.get("/privacy")
    assert response.status_code == 200
    assert '<meta name="description"' in response.text


def test_terms_has_meta_description(client: TestClient) -> None:
    response = client.get("/terms")
    assert response.status_code == 200
    assert '<meta name="description"' in response.text


@pytest.mark.parametrize("path", ["/", "/about", "/privacy", "/terms"])
def test_canonical_link_per_public_page(client: TestClient, path: str) -> None:
    """Every public page emits an absolute canonical link for its own URL."""
    response = client.get(path)
    assert response.status_code == 200
    expected = f'<link rel="canonical" href="http://localhost:8000{path}"'
    assert expected in response.text


@pytest.mark.parametrize("path", ["/", "/about", "/privacy", "/terms"])
def test_robots_meta_sitewide(client: TestClient, path: str) -> None:
    """Every public page emits the index,follow,max-image-preview:large robots meta."""
    response = client.get(path)
    assert response.status_code == 200
    assert '<meta name="robots" content="index,follow,max-image-preview:large"' in response.text


@pytest.mark.parametrize("path", ["/", "/about", "/privacy", "/terms"])
def test_json_ld_organization_sitewide(client: TestClient, path: str) -> None:
    """Every public page emits a parseable Organization JSON-LD block."""
    response = client.get(path)
    assert response.status_code == 200
    blocks = _json_ld_blocks(response.text)
    assert blocks, f"no JSON-LD blocks on {path}"
    org = next(
        (b for b in blocks if b.get("@type") == "Organization"),
        None,
    )
    assert org is not None, f"no Organization JSON-LD on {path}"
    assert org["name"] == "Odin"
    assert org["url"].startswith("http")


def _first(value: object) -> dict[str, Any]:
    """Unwrap a schema.org property that may be either a dict or a list of dicts."""
    if isinstance(value, list):
        assert value, "expected a non-empty list"
        first: object = value[0]  # pyright: ignore[reportUnknownVariableType]
    else:
        first = value
    assert isinstance(first, dict), "expected a dict"
    return cast("dict[str, Any]", first)


def test_json_ld_home_has_website_searchaction(client: TestClient) -> None:
    """Home page additionally emits a WebSite JSON-LD with a SearchAction."""
    response = client.get("/")
    blocks = _json_ld_blocks(response.text)
    website = next((b for b in blocks if b.get("@type") == "WebSite"), None)
    assert website is not None, "no WebSite JSON-LD on home"
    action = _first(website.get("potentialAction"))
    assert action.get("@type") == "SearchAction"
    target = action.get("target")
    target_str = target if isinstance(target, str) else _first(target).get("urlTemplate", "")
    assert "/profile?q={search_term_string}" in target_str


def test_json_ld_about_has_webapplication(client: TestClient) -> None:
    """About page emits a WebApplication JSON-LD with applicationCategory + offers."""
    response = client.get("/about")
    blocks = _json_ld_blocks(response.text)
    app_block = next((b for b in blocks if b.get("@type") == "WebApplication"), None)
    assert app_block is not None, "no WebApplication JSON-LD on /about"
    assert app_block.get("applicationCategory")
    assert app_block.get("browserRequirements")
    offers = _first(app_block.get("offers"))
    assert offers.get("price") in ("0", "0.00", 0)


def test_favicon_and_manifest_links_present(client: TestClient) -> None:
    """Base template emits SVG/PNG/apple favicons, manifest, and theme-color.

    djlint may wrap long `<link>` tags onto multiple lines, so attribute-presence
    is checked via a tag-bounded search rather than exact substring match.
    """
    body = client.get("/").text

    def _link_with_href(href: str) -> bool:
        return bool(re.search(r"<link\s[^>]*\bhref=" + re.escape(f'"{href}"'), body, re.DOTALL))

    assert _link_with_href("/static/favicon.svg")
    assert _link_with_href("/static/favicon-32x32.png")
    assert _link_with_href("/static/apple-touch-icon.png")
    assert _link_with_href("/site.webmanifest")
    assert '<meta name="theme-color"' in body


def test_robots_txt_has_sitemap_reference() -> None:
    """static/robots.txt includes the Sitemap: line and does not Disallow /login."""
    text = (STATIC_DIR / "robots.txt").read_text()
    sitemap_lines = [line for line in text.splitlines() if line.startswith("Sitemap:")]
    assert sitemap_lines, "robots.txt is missing a Sitemap: line"
    assert sitemap_lines[0].endswith("/sitemap.xml")
    assert "Disallow: /login" not in text


def test_sitemap_xml_contains_public_urls() -> None:
    """static/sitemap.xml lists absolute URLs for each public page."""
    text = (STATIC_DIR / "sitemap.xml").read_text()
    assert text.startswith("<?xml")
    assert "http://www.sitemaps.org/schemas/sitemap-0.9" in text
    locs = re.findall(r"<loc>([^<]+)</loc>", text)
    for path in ("/", "/about", "/privacy", "/terms"):
        assert any(loc.endswith(path) for loc in locs), f"sitemap.xml missing entry for {path}"


def test_site_webmanifest_is_valid_json() -> None:
    """static/site.webmanifest is valid JSON with the required keys."""
    data = json.loads((STATIC_DIR / "site.webmanifest").read_text())
    for key in ("name", "short_name", "icons", "start_url", "theme_color"):
        assert key in data, f"site.webmanifest missing key: {key}"
    assert isinstance(data["icons"], list)
    assert data["icons"]

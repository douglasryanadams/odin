"""Tests for the IndexNow ping script's sitemap-parsing and request-building logic."""

import json

import httpx
import pytest
import respx

from scripts.indexnow_ping import INDEXNOW_ENDPOINT, build_payload, parse_sitemap_urls, submit

_SITEMAP_XML = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap-0.9">
  <url>
    <loc>https://odinseye.info/</loc>
    <lastmod>2026-05-18</lastmod>
  </url>
  <url>
    <loc>https://odinseye.info/about</loc>
    <lastmod>2026-05-18</lastmod>
  </url>
</urlset>
"""

_EMPTY_SITEMAP_XML = (
    '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap-0.9"/>'
)


def test_parse_sitemap_urls_extracts_loc_elements_in_order() -> None:
    """<loc> text is returned in document order, ignoring <lastmod> and other tags."""
    assert parse_sitemap_urls(_SITEMAP_XML) == [
        "https://odinseye.info/",
        "https://odinseye.info/about",
    ]


def test_parse_sitemap_urls_empty_urlset_returns_empty_list() -> None:
    """A sitemap with no <url> entries parses to an empty list, not an error."""
    assert parse_sitemap_urls(_EMPTY_SITEMAP_XML) == []


def test_build_payload_shapes_the_indexnow_request() -> None:
    """The payload carries the host derived from the URLs, the key, keyLocation, and urlList."""
    urls = ["https://odinseye.info/", "https://odinseye.info/about"]

    payload = build_payload(urls, key="test-key-123")

    assert payload == {
        "host": "odinseye.info",
        "key": "test-key-123",
        "keyLocation": "https://odinseye.info/test-key-123.txt",
        "urlList": urls,
    }


def test_build_payload_rejects_empty_url_list() -> None:
    """An empty URL list is a caller bug, not something to silently no-op or send."""
    with pytest.raises(ValueError, match="empty"):
        build_payload([], key="test-key-123")


def test_build_payload_rejects_urls_on_different_hosts() -> None:
    """IndexNow's host field is singular; mixed-host input is a caller bug, not silently split."""
    urls = ["https://odinseye.info/", "https://example.com/other"]

    with pytest.raises(ValueError, match="host"):
        build_payload(urls, key="test-key-123")


@respx.mock
def test_submit_posts_json_payload_to_indexnow_endpoint() -> None:
    """submit() POSTs the exact payload as JSON to the IndexNow endpoint."""
    route = respx.post(INDEXNOW_ENDPOINT).mock(return_value=httpx.Response(200))
    payload: dict[str, str | list[str]] = {
        "host": "odinseye.info",
        "key": "test-key-123",
        "keyLocation": "https://odinseye.info/test-key-123.txt",
        "urlList": ["https://odinseye.info/"],
    }

    response = submit(payload)

    assert response.status_code == 200
    sent_request = route.calls.last.request
    assert sent_request.method == "POST"
    assert json.loads(sent_request.content) == payload


@respx.mock
def test_submit_raises_on_http_error_response() -> None:
    """A non-2xx IndexNow response raises, so the caller (deploy.sh) can log and continue."""
    respx.post(INDEXNOW_ENDPOINT).mock(return_value=httpx.Response(422))
    payload: dict[str, str | list[str]] = {
        "host": "odinseye.info",
        "key": "test-key-123",
        "keyLocation": "https://odinseye.info/test-key-123.txt",
        "urlList": ["https://odinseye.info/"],
    }

    with pytest.raises(httpx.HTTPStatusError):
        submit(payload)

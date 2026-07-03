"""Ping IndexNow with the sitemap's URL list.

Bing and Yandex can then index changes without waiting on their crawl
schedule; Google has not adopted IndexNow, so `static/sitemap.xml` remains
the source of truth for it. The sitemap is small and hand-maintained, so
this pings the full URL list on every deploy rather than detecting which
pages actually changed.

Run via `docker compose run` so the app image's httpx is available (see
`scripts/deploy.sh`, which calls this as a best-effort step after a deploy):

    docker compose ... run --rm -v "$(pwd)/scripts:/app/scripts:ro" web \
        python scripts/indexnow_ping.py
"""

from pathlib import Path
from urllib.parse import urlsplit
from xml.etree import ElementTree as ET

import httpx

# Generated once with `secrets.token_hex(16)`. Not sensitive: its only job is
# to live at a predictable public URL (static/<key>.txt) so IndexNow can
# confirm we own the domain. Rotate by regenerating both this constant and
# the key file together.
INDEXNOW_KEY = "0ed570a748cb78f46dec334dbb41b50c"

INDEXNOW_ENDPOINT = "https://api.indexnow.org/indexnow"

SITEMAP_PATH = Path(__file__).resolve().parent.parent / "static" / "sitemap.xml"

_SITEMAP_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap-0.9"}


def parse_sitemap_urls(sitemap_xml: str) -> list[str]:
    """Return every <loc> URL from a sitemap.xml document, in document order."""
    root = ET.fromstring(sitemap_xml)  # noqa: S314 - fixed, repo-owned input, not untrusted
    return [loc.text.strip() for loc in root.findall(".//sm:loc", _SITEMAP_NS) if loc.text]


def build_payload(urls: list[str], key: str) -> dict[str, str | list[str]]:
    """Build the IndexNow request body for a list of URLs on a single host."""
    if not urls:
        msg = "cannot ping IndexNow with an empty URL list"
        raise ValueError(msg)

    host = urlsplit(urls[0]).netloc
    mismatched = [url for url in urls if urlsplit(url).netloc != host]
    if mismatched:
        msg = f"all URLs must share host {host!r}; found a different host in {mismatched!r}"
        raise ValueError(msg)

    return {
        "host": host,
        "key": key,
        "keyLocation": f"https://{host}/{key}.txt",
        "urlList": urls,
    }


def submit(payload: dict[str, str | list[str]]) -> httpx.Response:
    """POST the payload to IndexNow. Raises httpx.HTTPStatusError on a non-2xx response."""
    response = httpx.post(INDEXNOW_ENDPOINT, json=payload, timeout=10.0)
    response.raise_for_status()
    return response


def main() -> None:
    """Ping IndexNow with every URL in static/sitemap.xml."""
    urls = parse_sitemap_urls(SITEMAP_PATH.read_text(encoding="utf-8"))
    payload = build_payload(urls, INDEXNOW_KEY)
    response = submit(payload)
    print(f"IndexNow: {response.status_code} for {len(urls)} URL(s)")


if __name__ == "__main__":
    main()

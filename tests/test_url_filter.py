"""Tests for the URL allowlist that gates search results before they reach Claude."""

from __future__ import annotations

import pytest

from odin.search import SearchResult
from odin.url_filter import filter_search_results, is_url_allowed


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        pytest.param("https://en.wikipedia.org/wiki/Ada_Lovelace", True, id="clean-https"),
        pytest.param("http://example.org/article", True, id="clean-http"),
        pytest.param("https://example.com/", True, id="root-path"),
        pytest.param("https://example.com/post?id=42", True, id="query-string"),
        pytest.param("https://example.com/post#section", True, id="fragment"),
        pytest.param("https://example.com/pdfs/article", True, id="extension-substring-in-path"),
        pytest.param("https://example.com/report.pdf", False, id="pdf"),
        pytest.param("https://example.com/REPORT.PDF", False, id="uppercase-pdf"),
        pytest.param("https://example.com/file.html.gz", False, id="trailing-gz"),
        pytest.param("https://example.com/installer.exe", False, id="exe"),
        pytest.param("https://example.com/bundle.zip", False, id="zip"),
        pytest.param("https://example.com/song.mp3", False, id="mp3"),
        pytest.param("https://example.com/image.png", False, id="png"),
        pytest.param("https://example.com/style.css", False, id="css"),
        pytest.param("https://example.com/app.js", False, id="js"),
        pytest.param("https://example.com/report.pdf?dl=1", False, id="pdf-with-query"),
        pytest.param("javascript:alert(1)", False, id="javascript-scheme"),
        pytest.param("data:text/html,<h1>x</h1>", False, id="data-scheme"),
        pytest.param("file:///etc/passwd", False, id="file-scheme"),
        pytest.param("ftp://example.com/x", False, id="ftp-scheme"),
        pytest.param("", False, id="empty-string"),
        pytest.param("not a url", False, id="malformed"),
        pytest.param("https://", False, id="no-host"),
    ],
)
def test_is_url_allowed_no_blocklist(url: str, *, expected: bool) -> None:
    """Allowlist decisions with an empty domain blocklist reflect scheme and extension only."""
    assert is_url_allowed(url, blocked_domains=()) is expected


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        pytest.param("https://bit.ly/abc123", False, id="exact-blocked-domain"),
        pytest.param("https://BIT.LY/abc123", False, id="uppercase-blocked-domain"),
        pytest.param("https://m.bit.ly/abc123", False, id="subdomain-of-blocked-domain"),
        pytest.param(
            "https://deep.sub.bit.ly/abc123", False, id="multi-level-subdomain-of-blocked-domain"
        ),
        pytest.param("https://bit.ly.evil.com/abc", True, id="blocked-as-prefix-only-is-allowed"),
        pytest.param("https://notbit.ly/abc", True, id="suffix-match-on-different-domain"),
        pytest.param("https://example.com/article", True, id="unrelated-domain"),
    ],
)
def test_is_url_allowed_with_blocklist(url: str, *, expected: bool) -> None:
    """Domain blocklist matches host exactly or as a parent of the host."""
    assert is_url_allowed(url, blocked_domains=("bit.ly",)) is expected


def test_filter_search_results_preserves_order_and_removes_blocked() -> None:
    """Allowed results survive in original order; blocked ones are dropped silently."""
    results = [
        SearchResult(url="https://example.com/a", title="a"),
        SearchResult(url="https://example.com/b.pdf", title="b"),
        SearchResult(url="https://bit.ly/c", title="c"),
        SearchResult(url="https://example.org/d", title="d"),
    ]
    filtered = filter_search_results(results, blocked_domains=("bit.ly",))
    assert [r.url for r in filtered] == [
        "https://example.com/a",
        "https://example.org/d",
    ]


def test_filter_search_results_empty_input() -> None:
    """An empty result list returns an empty list, not an error."""
    assert filter_search_results([], blocked_domains=()) == []

"""Tests for the fetch module."""

import httpx
import pytest
import respx

from odin.fetch import CONTENT_LIMIT, fetch_pages


@pytest.mark.asyncio
@respx.mock
async def test_fetch_pages_returns_content_for_each_url() -> None:
    """fetch_pages returns a dict entry with non-empty content for each URL."""
    respx.get("https://a.example.com").mock(
        return_value=httpx.Response(200, text="<p>Content A</p>")
    )
    respx.get("https://b.example.com").mock(
        return_value=httpx.Response(200, text="<p>Content B</p>")
    )

    result = await fetch_pages(["https://a.example.com", "https://b.example.com"])

    assert set(result.keys()) == {"https://a.example.com", "https://b.example.com"}
    assert len(result["https://a.example.com"]) > 0
    assert len(result["https://b.example.com"]) > 0


@pytest.mark.asyncio
@respx.mock
async def test_fetch_pages_caps_content_at_limit() -> None:
    """fetch_pages returns at most _CONTENT_LIMIT characters per URL."""
    respx.get("https://example.com").mock(return_value=httpx.Response(200, text="x" * 50_000))

    result = await fetch_pages(["https://example.com"])

    assert len(result["https://example.com"]) <= CONTENT_LIMIT


@pytest.mark.asyncio
@respx.mock
async def test_fetch_pages_captures_error_without_failing_batch() -> None:
    """fetch_pages stores an error string for a failed URL without raising."""
    respx.get("https://ok.example.com").mock(
        return_value=httpx.Response(200, text="<p>Good content</p>")
    )
    respx.get("https://bad.example.com").mock(return_value=httpx.Response(404))

    result = await fetch_pages(["https://ok.example.com", "https://bad.example.com"])

    assert len(result["https://ok.example.com"]) > 0
    assert "Error" in result["https://bad.example.com"]

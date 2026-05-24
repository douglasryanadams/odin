"""Allowlist gate for URLs that may be sent to Claude.

A URL passes the gate when all three are true:

1. Scheme is ``http`` or ``https``. ``javascript:``, ``data:``, ``file:``, and
   ``ftp://`` URLs cannot serve text we want Claude to summarize and they
   widen the prompt-injection surface.
2. Path does not end in a known-binary extension. We reject document
   archives, executables, media, fonts, and static assets — anything that
   would arrive as bytes, not prose. The check is case-insensitive and
   inspects only the URL path (query string and fragment are ignored).
3. Host is not in (or a subdomain of) the configured ``blocked_domains``.
   URL shorteners and public paste hosts are the natural channels for
   adversaries to drop attacker-controlled text into a search index without
   owning a registrable domain.

Domain matching is anchored: ``bit.ly`` blocks ``bit.ly`` and
``m.bit.ly`` but not ``bit.ly.evil.com``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from odin.search import SearchResult


_ALLOWED_SCHEMES = frozenset({"http", "https"})

BLOCKED_EXTENSIONS: frozenset[str] = frozenset(
    {
        # Documents
        ".pdf",
        ".doc",
        ".docx",
        ".xls",
        ".xlsx",
        ".ppt",
        ".pptx",
        ".odt",
        ".ods",
        ".odp",
        ".rtf",
        # Archives
        ".zip",
        ".tar",
        ".gz",
        ".tgz",
        ".bz2",
        ".7z",
        ".rar",
        ".iso",
        # Executables / installers
        ".dmg",
        ".exe",
        ".msi",
        ".deb",
        ".rpm",
        ".apk",
        ".jar",
        # Audio / video
        ".mp3",
        ".mp4",
        ".m4a",
        ".wav",
        ".ogg",
        ".webm",
        ".mov",
        ".avi",
        ".mkv",
        # Images
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".svg",
        ".ico",
        ".bmp",
        ".tiff",
        # Fonts
        ".woff",
        ".woff2",
        ".ttf",
        ".otf",
        # Web assets
        ".css",
        ".js",
        ".mjs",
        ".map",
        # Data
        ".json",
        ".xml",
        ".rss",
        ".atom",
        ".csv",
    }
)


def _path_has_blocked_extension(path: str) -> bool:
    lowered = path.lower()
    return any(lowered.endswith(ext) for ext in BLOCKED_EXTENSIONS)


def _host_in_blocklist(host: str, blocked_domains: Iterable[str]) -> bool:
    host = host.lower()
    for blocked in blocked_domains:
        blocked_lower = blocked.lower().strip(".")
        if not blocked_lower:
            continue
        if host == blocked_lower or host.endswith("." + blocked_lower):
            return True
    return False


def is_url_allowed(url: str, *, blocked_domains: Iterable[str]) -> bool:
    """Return True when the URL passes the scheme, extension, and domain gates."""
    if not url:
        return False
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    if parts.scheme not in _ALLOWED_SCHEMES:
        return False
    if not parts.hostname:
        return False
    if _path_has_blocked_extension(parts.path):
        return False
    return not _host_in_blocklist(parts.hostname, blocked_domains)


def filter_search_results(
    results: Sequence[SearchResult],
    *,
    blocked_domains: Iterable[str],
) -> list[SearchResult]:
    """Drop results whose URL fails :func:`is_url_allowed`, preserving order."""
    blocked = tuple(blocked_domains)
    return [r for r in results if is_url_allowed(r.url, blocked_domains=blocked)]

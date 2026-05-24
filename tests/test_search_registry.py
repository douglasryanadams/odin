"""Tests for the backend registry factories: enable-gating from config."""

from odin import search
from odin.config import Settings
from odin.search import WikipediaBackend

_APP_URL = "https://example.com"
_VALID_SECRET = "x" * 32


def _settings(**overrides: object) -> Settings:
    return Settings(secret_key=_VALID_SECRET, app_url=_APP_URL, **overrides)  # type: ignore[arg-type]


def test_wikipedia_factory_returns_none_when_disabled() -> None:
    """With wikipedia_enabled False the backend is never built."""
    settings = _settings(wikipedia_enabled=False)
    assert search._wikipedia_factory(settings) is None  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]


def test_wikipedia_factory_builds_backend_when_enabled() -> None:
    """Enabled yields a WikipediaBackend carrying a User-Agent built from config."""
    settings = _settings(wikipedia_enabled=True)
    backend = search._wikipedia_factory(settings)  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
    assert isinstance(backend, WikipediaBackend)
    assert backend.user_agent == f"Odin/1.0 (+{_APP_URL}; {settings.contact_email}) httpx"
    assert backend.timeout_seconds == settings.search_timeout_seconds

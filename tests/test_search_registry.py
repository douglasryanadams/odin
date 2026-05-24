"""Tests for the backend registry factories: fail-closed gating from config."""

from odin import search
from odin.config import Settings
from odin.search import BraveBackend, WikipediaBackend

_APP_URL = "https://example.com"
_VALID_SECRET = "x" * 32


def _settings(**overrides: object) -> Settings:
    return Settings(secret_key=_VALID_SECRET, app_url=_APP_URL, **overrides)  # type: ignore[arg-type]


def test_brave_factory_returns_none_without_api_key() -> None:
    """No BRAVE_API_KEY in config means the Brave backend is never built."""
    settings = _settings(brave_api_key=None)
    assert search._brave_factory(settings) is None  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]


def test_brave_factory_builds_backend_when_api_key_present() -> None:
    """Given a key, the factory yields a BraveBackend carrying it."""
    settings = _settings(brave_api_key="test-key")
    backend = search._brave_factory(settings)  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
    assert isinstance(backend, BraveBackend)
    assert backend.api_key == "test-key"
    assert backend.timeout_seconds == settings.search_timeout_seconds


def test_wikipedia_factory_always_builds_backend() -> None:
    """Wikipedia needs no credentials; the factory always yields a backend."""
    settings = _settings()
    backend = search._wikipedia_factory(settings)  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
    assert isinstance(backend, WikipediaBackend)
    assert backend.user_agent == f"Odin/1.0 (+{_APP_URL}; {settings.contact_email}) httpx"
    assert backend.timeout_seconds == settings.search_timeout_seconds

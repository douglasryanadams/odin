"""Tests for application settings validation."""

import pytest
from pydantic import ValidationError

from odin.config import Settings

_APP_URL = "https://example.com"
_VALID_SECRET = "x" * 32


def test_secret_key_below_32_chars_rejected() -> None:
    """A short secret_key fails validation: HMAC-SHA256 needs 256 bits of entropy."""
    with pytest.raises(ValidationError, match="secret_key"):
        Settings(secret_key="too-short", app_url=_APP_URL)  # noqa: S106


def test_secret_key_at_32_chars_accepted() -> None:
    """Exactly 32 chars satisfies the minimum length."""
    settings = Settings(secret_key=_VALID_SECRET, app_url=_APP_URL)
    assert len(settings.secret_key) == 32


def test_cookie_secure_defaults_false() -> None:
    """Default is False so plain-HTTP local dev still works."""
    settings = Settings(secret_key=_VALID_SECRET, app_url=_APP_URL)
    assert settings.cookie_secure is False


def test_cookie_secure_can_be_enabled() -> None:
    """Production sets cookie_secure=True via env var."""
    settings = Settings(secret_key=_VALID_SECRET, app_url=_APP_URL, cookie_secure=True)
    assert settings.cookie_secure is True

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


def test_cookie_secure_defaults_true(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default is True so production is secure by default; a missing env var fails closed."""
    monkeypatch.delenv("COOKIE_SECURE", raising=False)
    # _env_file=None bypasses the on-disk .env so we exercise the code default,
    # not a developer's local override.
    settings = Settings(secret_key=_VALID_SECRET, app_url=_APP_URL, _env_file=None)  # type: ignore[call-arg]
    assert settings.cookie_secure is True


def test_cookie_secure_can_be_disabled() -> None:
    """Local plain-HTTP dev sets cookie_secure=False via env var."""
    settings = Settings(secret_key=_VALID_SECRET, app_url=_APP_URL, cookie_secure=False)
    assert settings.cookie_secure is False


def test_smtp_defaults_purelymail() -> None:
    """SMTP host/port/from default to Purelymail and odinseye.info."""
    settings = Settings(secret_key=_VALID_SECRET, app_url=_APP_URL)
    assert settings.smtp_host == "smtp.purelymail.com"
    assert settings.smtp_port == 587
    assert settings.smtp_from == "odin@odinseye.info"


def test_contact_email_default() -> None:
    """Contact email defaults to odin@odinseye.info."""
    settings = Settings(secret_key=_VALID_SECRET, app_url=_APP_URL)
    assert settings.contact_email == "odin@odinseye.info"


def test_smtp_host_override() -> None:
    """Self-hosters can override SMTP host and from address."""
    settings = Settings(
        secret_key=_VALID_SECRET,
        app_url=_APP_URL,
        smtp_host="mail.example.org",
        smtp_from="bot@example.org",
    )
    assert settings.smtp_host == "mail.example.org"
    assert settings.smtp_from == "bot@example.org"


def test_contact_email_override() -> None:
    """Self-hosters can override the displayed contact email."""
    settings = Settings(
        secret_key=_VALID_SECRET,
        app_url=_APP_URL,
        contact_email="hi@example.org",
    )
    assert settings.contact_email == "hi@example.org"

"""Tests for SMTP magic-link delivery gating and configuration."""

from unittest.mock import MagicMock, patch

import pytest

from odin import email as _email
from odin.config import settings


@pytest.mark.asyncio
async def test_send_magic_link_skips_without_smtp_user() -> None:
    """No SMTP_USER means dev mode: no connection attempt, link logged only."""
    with (
        patch.object(settings, "smtp_user", None),
        patch.object(settings, "smtp_pass", None),
        patch("odin.email.smtplib.SMTP") as mock_smtp,
    ):
        await _email.send_magic_link("user@example.com", "https://example.com/verify?t=x")
    mock_smtp.assert_not_called()


@pytest.mark.asyncio
async def test_send_magic_link_sends_when_smtp_user_set() -> None:
    """When credentials are present, connect to the configured host/port and login."""
    smtp_instance = MagicMock()
    smtp_cm = MagicMock()
    smtp_cm.__enter__ = MagicMock(return_value=smtp_instance)
    smtp_cm.__exit__ = MagicMock(return_value=False)

    with (
        patch.object(settings, "smtp_host", "smtp.purelymail.com"),
        patch.object(settings, "smtp_port", 587),
        patch.object(settings, "smtp_from", "odin@odinseye.info"),
        patch.object(settings, "smtp_user", "odin@odinseye.info"),
        patch.object(settings, "smtp_pass", "secret"),
        patch("odin.email.smtplib.SMTP", return_value=smtp_cm) as mock_smtp,
    ):
        await _email.send_magic_link("user@example.com", "https://example.com/verify?t=x")

    mock_smtp.assert_called_once_with("smtp.purelymail.com", 587)
    smtp_instance.starttls.assert_called_once()
    smtp_instance.login.assert_called_once_with("odin@odinseye.info", "secret")
    smtp_instance.send_message.assert_called_once()

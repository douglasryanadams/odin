"""Tests for SMTP magic-link delivery gating and configuration."""

from unittest.mock import MagicMock, patch

import pytest
from loguru import logger

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


@pytest.mark.asyncio
async def test_send_magic_link_sends_multipart_text_and_html() -> None:
    """Delivered message must carry both a text/plain and a text/html part containing the link."""
    smtp_instance = MagicMock()
    smtp_cm = MagicMock()
    smtp_cm.__enter__ = MagicMock(return_value=smtp_instance)
    smtp_cm.__exit__ = MagicMock(return_value=False)

    link = "https://odinseye.info/auth/verify?token=abc.def"
    with (
        patch.object(settings, "smtp_user", "odin@odinseye.info"),
        patch.object(settings, "smtp_pass", "secret"),
        patch("odin.email.smtplib.SMTP", return_value=smtp_cm),
    ):
        await _email.send_magic_link("user@example.com", link)

    sent_message = smtp_instance.send_message.call_args.args[0]
    assert sent_message.is_multipart(), "magic-link email must be multipart/alternative"

    text_part = next(p for p in sent_message.iter_parts() if p.get_content_type() == "text/plain")
    html_part = next(p for p in sent_message.iter_parts() if p.get_content_type() == "text/html")
    assert link in text_part.get_content()
    assert link in html_part.get_content()


@pytest.mark.asyncio
async def test_send_magic_link_warns_when_smtp_unset() -> None:
    """Misconfigured prod (SMTP_USER unset) must emit a WARNING, not just a DEBUG line."""
    records: list[dict[str, object]] = []
    sink_id = logger.add(
        lambda msg: records.append(
            {"level": msg.record["level"].name, "message": msg.record["message"]}
        ),
        level="DEBUG",
    )
    try:
        with patch.object(settings, "smtp_user", None), patch.object(settings, "smtp_pass", None):
            await _email.send_magic_link("user@example.com", "https://example.com/verify?t=x")
    finally:
        logger.remove(sink_id)

    warnings = [r for r in records if r["level"] == "WARNING"]
    assert len(warnings) == 1, f"expected exactly one WARNING, got {records}"
    assert "SMTP" in str(warnings[0]["message"])


def test_html_template_contains_button_anchor_and_expiry_copy() -> None:
    """The rendered HTML body must link the button to the magic link and disclose the expiry."""
    link = "https://odinseye.info/auth/verify?token=abc.def"
    html = _email.render_magic_link_html(link)
    assert f'href="{link}"' in html
    assert "15 minutes" in html

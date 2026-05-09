"""Magic link email delivery."""

import asyncio
import smtplib
from email.message import EmailMessage

from loguru import logger

from odin.config import settings

_SUBJECT = "Your Odin sign-in link"
_BODY = "Click to sign in to Odin:\n\n{link}\n\nThis link expires in 15 minutes."


async def send_magic_link(to: str, link: str) -> None:
    """Send a magic sign-in link.

    Logs the link to the console when SMTP credentials are not configured (development).
    """
    if settings.smtp_user:
        await asyncio.to_thread(_send_smtp, to, link)
    else:
        logger.debug("magic link for {}: {}", to, link)


def _send_smtp(to: str, link: str) -> None:
    msg = EmailMessage()
    msg["Subject"] = _SUBJECT
    msg["From"] = settings.smtp_from
    msg["To"] = to
    msg.set_content(_BODY.format(link=link))

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as smtp:  # type: ignore[arg-type]
        smtp.starttls()
        if settings.smtp_user:
            smtp.login(settings.smtp_user, settings.smtp_pass or "")
        smtp.send_message(msg)

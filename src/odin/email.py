"""Magic link email delivery."""

import asyncio
import smtplib
from email.message import EmailMessage
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from loguru import logger

from odin.config import settings

_SUBJECT = "Sign in to Odin"
_TEMPLATE_DIR = Path(__file__).parent / "templates" / "email"
_jinja = Environment(
    loader=FileSystemLoader(_TEMPLATE_DIR),
    autoescape=select_autoescape(["html"]),
)


def render_magic_link_text(link: str) -> str:
    """Render the plain-text magic-link body."""
    return _jinja.get_template("magic_link.txt.j2").render(
        link=link, contact_email=settings.contact_email
    )


def render_magic_link_html(link: str) -> str:
    """Render the HTML magic-link body."""
    return _jinja.get_template("magic_link.html.j2").render(
        link=link, contact_email=settings.contact_email
    )


async def send_magic_link(to: str, link: str) -> None:
    """Send a magic sign-in link.

    Logs the link to the console when SMTP credentials are not configured (development).
    """
    if settings.smtp_user:
        await asyncio.to_thread(_send_smtp, to, link)
    else:
        logger.warning("SMTP_USER is not configured; magic link will not be sent to {}", to)
        logger.debug("magic link for {}: {}", to, link)


def _send_smtp(to: str, link: str) -> None:
    msg = EmailMessage()
    msg["Subject"] = _SUBJECT
    msg["From"] = settings.smtp_from
    msg["To"] = to
    msg.set_content(render_magic_link_text(link))
    msg.add_alternative(render_magic_link_html(link), subtype="html")

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as smtp:  # type: ignore[arg-type]
        smtp.starttls()
        if settings.smtp_user:
            smtp.login(settings.smtp_user, settings.smtp_pass or "")
        smtp.send_message(msg)

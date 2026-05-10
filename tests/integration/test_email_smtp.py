"""Integration test that performs a real SMTP send.

Requires SMTP_TEST_RECIPIENT to be set so each developer sends to their own
inbox instead of a shared address. The test skips (with a loud reason) when
the variable is missing so `make test` passes by default; the skip message
tells the developer exactly what to export to opt in.
"""

import asyncio
import os
import secrets

import pytest

from odin import auth, email
from odin.config import settings


@pytest.mark.integration
def test_send_real_magic_link_to_configured_recipient() -> None:
    """Send a real magic-link email via the configured SMTP server.

    The test only validates that the SMTP transaction completed without
    raising; deliverability must be verified by the developer's inbox.
    """
    recipient = os.environ.get("SMTP_TEST_RECIPIENT")
    if not recipient:
        pytest.skip(
            "SMTP_TEST_RECIPIENT is not set. "
            "Export your own email address (e.g. SMTP_TEST_RECIPIENT=you@example.com) "
            "to run this test; do not commit a value."
        )
    if not settings.smtp_user or not settings.smtp_pass:
        pytest.skip(
            "SMTP_USER and SMTP_PASS must be configured in .env or the environment "
            "to run this test."
        )

    token = auth.generate_magic_token(recipient, settings.secret_key.encode())
    link = f"{settings.app_url.rstrip('/')}/auth/verify?token={token}&trace={secrets.token_hex(4)}"

    asyncio.run(email.send_magic_link(recipient, link))

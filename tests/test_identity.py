"""Tests for the shared identity hash that keys a user across ValKey and Postgres."""

from odin.identity import hash_email


def test_hash_email_is_case_insensitive() -> None:
    """Differently-cased addresses must hash identically.

    The same person searching as "User@Example.com" and "user@example.com"
    must land on the same key in both stores — a missing .lower() here would
    silently fragment that user's rate limits and history in two places.
    """
    assert hash_email("User@Example.com") == hash_email("user@example.com")


def test_hash_email_is_deterministic_and_truncated_to_16_hex_chars() -> None:
    """The digest is stable across calls and truncated to the documented 16 hex chars."""
    digest = hash_email("user@example.com")

    assert digest == hash_email("user@example.com")
    assert len(digest) == 16
    assert all(char in "0123456789abcdef" for char in digest)


def test_hash_email_distinguishes_different_addresses() -> None:
    """Distinct addresses must not collide on the same hash."""
    assert hash_email("user@example.com") != hash_email("other@example.com")

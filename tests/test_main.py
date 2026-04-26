"""Tests for the main application module."""

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_health() -> None:
    """Verify the health endpoint returns 200 with status ok."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

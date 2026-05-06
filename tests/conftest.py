"""Pytest configuration."""

import os

os.environ.setdefault("LOG_LEVEL", "DEBUG")
os.environ.setdefault("SECRET_KEY", "test-only-insecure-secret-key-do-not-use")
os.environ.setdefault("APP_URL", "http://localhost:8000")

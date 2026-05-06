"""Application settings loaded from environment variables at startup."""

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables at startup."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    log_level: str = "INFO"

    playwright_headless: bool = True
    playwright_trace_dir: str | None = None

    searxng_url: str = "http://searxng:8080"

    secret_key: str  # required — startup fails if unset
    app_url: str  # required — used in magic link URLs; no safe generic default

    odin_valkey_url: str = "redis://odin-valkey:6379"

    anon_daily_limit: int = Field(default=3, ge=0)
    auth_daily_limit: int = Field(default=20, ge=0)

    smtp_host: str | None = None
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_from: str | None = None
    smtp_user: str | None = None
    smtp_pass: str | None = None

    @model_validator(mode="after")
    def _smtp_from_required_with_host(self) -> "Settings":
        if self.smtp_host and not self.smtp_from:
            msg = "SMTP_FROM is required when SMTP_HOST is set"
            raise ValueError(msg)
        return self


settings = Settings()  # pyright: ignore[reportCallIssue]

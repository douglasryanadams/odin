"""Application settings loaded from environment variables at startup."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables at startup."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    log_level: str = "INFO"

    playwright_headless: bool = True
    playwright_trace_dir: str | None = None

    searxng_url: str = "http://searxng:8080"

    secret_key: str = Field(min_length=32)  # required; HMAC-SHA256 needs 256 bits of entropy
    app_url: str  # required — used in magic link URLs; no safe generic default

    cookie_secure: bool = False  # set true in prod so Set-Cookie includes Secure

    odin_valkey_url: str = "redis://odin-valkey:6379"

    anon_daily_limit: int = Field(default=3, ge=0)
    auth_daily_limit: int = Field(default=20, ge=0)

    # Magic-link delivery defaults to Purelymail; override host/from for other providers.
    # Without SMTP_USER/SMTP_PASS the link is logged instead of sent (dev mode).
    smtp_host: str = "smtp.purelymail.com"
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_from: str = "odin@odinseye.info"
    smtp_user: str | None = None
    smtp_pass: str | None = None

    contact_email: str = "odin@odinseye.info"


settings = Settings()  # pyright: ignore[reportCallIssue]

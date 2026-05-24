"""Application settings loaded from environment variables at startup."""

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Seed for the URL domain blocklist. Targets the channels adversaries can
# trivially drop attacker-controlled text into without owning a domain:
# URL shorteners (which also hide the destination from select_urls) and
# public paste/snippet hosts. Operators can extend or replace via the
# URL_DOMAIN_BLOCKLIST env var.
_DEFAULT_URL_DOMAIN_BLOCKLIST: tuple[str, ...] = (
    # URL shorteners
    "bit.ly",
    "tinyurl.com",
    "t.co",
    "goo.gl",
    "ow.ly",
    "is.gd",
    "buff.ly",
    # Public paste / snippet hosts
    "pastebin.com",
    "paste.ee",
    "hastebin.com",
    "ghostbin.com",
    "rentry.co",
)


class Settings(BaseSettings):
    """Application settings loaded from environment variables at startup."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    log_level: str = "INFO"

    playwright_headless: bool = True
    playwright_trace_dir: str | None = None
    # Channel for chromium.launch(). None uses Playwright's bundled Chromium.
    playwright_channel: str | None = None
    playwright_storage_state_path: str | None = "/var/lib/odin/playwright-state/state.json"
    fetch_curl_cffi_enabled: bool = True

    search_timeout_seconds: float = Field(default=30.0, gt=0)  # per-backend call ceiling

    # Brave Search API. Fails closed without a key: the backend is not constructed.
    brave_api_key: str | None = None

    secret_key: str = Field(min_length=32)  # required; HMAC-SHA256 needs 256 bits of entropy
    app_url: str  # required — used in magic link URLs; no safe generic default

    cookie_secure: bool = True  # secure-by-default; set false for plain-HTTP local dev

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

    # Hosts whose URLs are dropped from search results before they reach
    # Claude. See _DEFAULT_URL_DOMAIN_BLOCKLIST for the seeded set. Override
    # via URL_DOMAIN_BLOCKLIST as a comma-separated list; the empty string
    # clears the list entirely.
    url_domain_blocklist: tuple[str, ...] = _DEFAULT_URL_DOMAIN_BLOCKLIST

    @field_validator("url_domain_blocklist", mode="before")
    @classmethod
    def _parse_url_domain_blocklist(cls, value: object) -> object:
        # Only intercept the env-var (string) path; tuples/lists go through
        # pydantic's normal validation. The seeded default is already lowercase.
        if isinstance(value, str):
            return tuple(part.strip().lower() for part in value.split(",") if part.strip())
        return value


settings = Settings()  # pyright: ignore[reportCallIssue]

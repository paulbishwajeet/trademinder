from pathlib import Path

import re

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_ROOT_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ROOT_ENV_FILE, env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+asyncpg://trademinder:password@localhost:5432/trademinder"
    secret_key: str = "changeme"
    anthropic_api_key: str = ""
    schwab_app_key: str = ""
    schwab_app_secret: str = ""
    # Market data provider behind app.services.market_data. Only "schwab" exists today; anything
    # else fails at startup rather than at the first market data call.
    market_data_provider: str = "schwab"
    # Token follower (dev only): production's origin, e.g. https://tm.example.com. Set → this environment never
    # calls Schwab's token endpoint and pulls the token pair from production instead. Unset → today's behavior.
    schwab_token_sync_url: str = ""
    # Shared secret (32+ characters) for the token export. Production: enables POST /api/market-data/sync/tokens.
    # Dev: sent with each pull. Never logged.
    schwab_token_sync_secret: str = ""

    # Seeds the first (admin) user in migration 015. That row is the bootstrap admin: the first Google
    # sign-in with this email binds to it (and so to the existing data).
    owner_email: str = ""
    owner_display_name: str = "Owner"

    # ── Login (Part 5) ──
    # The public https origin (Traefik), e.g. https://tm.example.com. Redirect URIs and the Secure cookie
    # flag are derived from it. http://localhost:5430 for local dev.
    public_base_url: str = "http://localhost:5430"
    google_client_id: str = ""
    google_client_secret: str = ""
    session_days: int = 30
    # Signs the short-lived login state cookie (PKCE verifier, state, nonce). openssl rand -hex 32
    auth_state_secret: str = "dev-only-change-me"
    # Comma-separated Chrome extension IDs allowed to receive extension tokens (and CORS origins).
    extension_ids: str = ""

    alert_engine_interval_minutes: int = 15
    market_hours_start: str = "09:30"
    market_hours_end: str = "16:00"
    price_refresh_interval_minutes: int = 15
    briefing_generate_time: str = "08:00"

    @field_validator("market_data_provider")
    @classmethod
    def _known_provider(cls, value: str) -> str:
        name = value.strip().lower()
        if name not in ("schwab",):
            raise ValueError(f"Unknown MARKET_DATA_PROVIDER {value!r}; supported: schwab")
        return name


    @field_validator("public_base_url")
    @classmethod
    def _origin_only(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        if not re.fullmatch(r"https?://[A-Za-z0-9.\-]+(:\d+)?", value):
            raise ValueError("PUBLIC_BASE_URL must be an origin like https://tm.example.com")
        return value

    @model_validator(mode="after")
    def _token_sync(self):
        """Refuse to start with a half or weak token-sync configuration."""
        self.schwab_token_sync_url = self.schwab_token_sync_url.strip().rstrip("/")
        self.schwab_token_sync_secret = self.schwab_token_sync_secret.strip()
        if self.schwab_token_sync_secret and len(self.schwab_token_sync_secret) < 32:
            raise ValueError("SCHWAB_TOKEN_SYNC_SECRET must be at least 32 characters (openssl rand -hex 32)")
        url = self.schwab_token_sync_url
        if url:
            if not self.schwab_token_sync_secret:
                raise ValueError("SCHWAB_TOKEN_SYNC_URL is set (token follower mode) but SCHWAB_TOKEN_SYNC_SECRET is not")
            local = re.fullmatch(r"http://(localhost|127\.0\.0\.1)(:\d+)?", url)
            if not (local or re.fullmatch(r"https://[A-Za-z0-9.\-]+(:\d+)?", url)):
                raise ValueError(
                    "SCHWAB_TOKEN_SYNC_URL must be production's https origin, e.g. https://tm.example.com "
                    "(plain http only for localhost)"
                )
        return self

    @model_validator(mode="after")
    def _https_needs_google(self):
        """Fail fast: a production (https) deployment without Google sign-in configured can't log anyone in."""
        if self.public_base_url.startswith("https://"):
            missing = [name for name, value in (
                ("GOOGLE_CLIENT_ID", self.google_client_id),
                ("GOOGLE_CLIENT_SECRET", self.google_client_secret),
            ) if not value.strip()]
            if self.auth_state_secret in ("", "dev-only-change-me") or len(self.auth_state_secret) < 32:
                missing.append("AUTH_STATE_SECRET (32+ random characters)")
            if missing:
                raise ValueError(f"PUBLIC_BASE_URL is https but these are not set: {', '.join(missing)}")
        return self

    @property
    def token_follower(self) -> bool:
        """Dev mode: pull Schwab tokens from production instead of refreshing (or reconnecting) here."""
        return bool(self.schwab_token_sync_url)

    @property
    def token_export_enabled(self) -> bool:
        """Production: serve the token pair to followers. Never on a follower itself."""
        return bool(self.schwab_token_sync_secret) and not self.token_follower

    @property
    def secure_cookies(self) -> bool:
        return self.public_base_url.startswith("https://")

    @property
    def extension_id_list(self) -> list[str]:
        return [x.strip() for x in self.extension_ids.split(",") if x.strip()]


settings = Settings()

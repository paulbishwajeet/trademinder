from pathlib import Path

from pydantic import field_validator
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

    # Used only by migration 015 to seed the first (admin) user, and by the
    # current-user seam to find that user until real login lands (Part 5).
    owner_email: str = ""
    owner_display_name: str = "Owner"

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


settings = Settings()

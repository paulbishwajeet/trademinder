from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_ROOT_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ROOT_ENV_FILE, env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+asyncpg://trademinder:password@localhost:5432/trademinder"
    secret_key: str = "changeme"
    anthropic_api_key: str = ""
    schwab_app_key: str = ""
    schwab_app_secret: str = ""

    alert_engine_interval_minutes: int = 15
    market_hours_start: str = "09:30"
    market_hours_end: str = "16:00"
    price_refresh_interval_minutes: int = 15
    briefing_generate_time: str = "08:00"


settings = Settings()

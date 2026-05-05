from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+asyncpg://trademinder:password@localhost:5432/trademinder"
    secret_key: str = "changeme"
    anthropic_api_key: str = ""

    alert_engine_interval_minutes: int = 15
    market_hours_start: str = "09:30"
    market_hours_end: str = "16:00"
    price_refresh_interval_minutes: int = 15
    briefing_generate_time: str = "08:00"


settings = Settings()

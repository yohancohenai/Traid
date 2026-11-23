"""Application configuration. All secrets come from environment variables."""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="TTQ_", extra="ignore")

    env: str = "development"
    database_url: str = "postgresql+psycopg://ttq:ttq@localhost:5432/ttq"
    redis_url: str = "redis://localhost:6379/0"
    artifacts_dir: str = "./artifacts"

    # Auth (single operator account). Password hash preferred; plain password allowed for dev.
    admin_username: str = "admin"
    admin_password: str = "change-me"
    admin_password_hash: str | None = None
    jwt_secret: str = "dev-insecure-secret-change-me"
    jwt_expire_minutes: int = 720

    user_timezone: str = "America/New_York"
    user_region: str = "US-FL"

    # Odds freshness: a quote older than this (seconds) can never be VERIFIED.
    max_quote_age_seconds: int = 600

    # Provider credentials (optional). Unset -> adapter reports UNAVAILABLE.
    the_odds_api_key: str | None = None
    the_odds_api_sport_key: str | None = None  # must be confirmed via /v4/sports
    oddspapi_api_key: str | None = None
    oddspapi_base_url: str = "https://api.oddspapi.io/v4"

    # Alerts
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    alert_email_to: str | None = None
    alert_email_from: str | None = None
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None

    cors_origins: str = "http://localhost:3000"
    enable_demo: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()

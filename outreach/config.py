import secrets
from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://outreach:outreach@localhost:5432/outreach"
    # An ephemeral secret keeps evaluation deployments from falling back to a
    # known key. Set APP_SECRET explicitly when tokens must survive restarts.
    app_secret: str = Field(default_factory=lambda: secrets.token_urlsafe(48), min_length=24)
    environment: str = "development"
    demo_auth_enabled: bool = False
    access_token_minutes: int = 60
    default_timezone: str = "Asia/Kolkata"
    queue_lease_seconds: int = 90
    persistence_enabled: bool = False
    background_workers_enabled: bool = False
    worker_interval_seconds: int = 30

    @field_validator("database_url")
    @classmethod
    def normalize_async_database_url(cls, value: str) -> str:
        """Accept standard Supabase/Postgres URLs with SQLAlchemy asyncpg."""
        if value.startswith("postgres://"):
            value = "postgresql://" + value.removeprefix("postgres://")
        if value.startswith("postgresql://"):
            value = "postgresql+asyncpg://" + value.removeprefix("postgresql://")
        # Supabase connection strings commonly use libpq's sslmode spelling;
        # asyncpg expects ssl.
        value = value.replace("sslmode=require", "ssl=require")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()

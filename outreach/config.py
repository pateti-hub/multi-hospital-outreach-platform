import secrets
from functools import lru_cache

from pydantic import Field
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


@lru_cache
def get_settings() -> Settings:
    return Settings()

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://outreach:outreach@localhost:5432/outreach"
    app_secret: str = Field(
        default="local-development-secret-change-before-deploying", min_length=24
    )
    environment: str = "development"
    demo_auth_enabled: bool = False
    access_token_minutes: int = 60
    default_timezone: str = "Asia/Kolkata"
    queue_lease_seconds: int = 90


@lru_cache
def get_settings() -> Settings:
    return Settings()
from __future__ import annotations

from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from outreach.config import get_settings
from outreach.models import Base


@lru_cache
def engine() -> AsyncEngine:
    return create_async_engine(
        get_settings().database_url,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
    )


@lru_cache
def session_factory() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine(), expire_on_commit=False)


async def initialize_database() -> None:
    """Create prototype tables; production deployments should use migrations."""
    async with engine().begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


async def close_database() -> None:
    if engine.cache_info().currsize:
        await engine().dispose()
    engine.cache_clear()
    session_factory.cache_clear()

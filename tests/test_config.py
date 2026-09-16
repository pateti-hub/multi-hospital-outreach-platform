from outreach.config import Settings


def test_supabase_postgres_url_uses_asyncpg() -> None:
    settings = Settings(database_url="postgresql://user:password@example.supabase.co:5432/postgres")
    assert settings.database_url.startswith("postgresql+asyncpg://")


def test_legacy_postgres_scheme_and_sslmode_are_normalized() -> None:
    settings = Settings(
        database_url="postgres://user:password@example.test/postgres?sslmode=require"
    )
    assert settings.database_url == (
        "postgresql+asyncpg://user:password@example.test/postgres?ssl=require"
    )


def test_existing_asyncpg_url_is_preserved() -> None:
    value = "postgresql+asyncpg://user:password@localhost:5432/outreach"
    assert Settings(database_url=value).database_url == value

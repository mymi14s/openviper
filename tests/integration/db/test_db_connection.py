import pytest

from openviper.db.connection import _create_engine


def _asyncpg_dialect_available() -> bool:
    """Return True if the postgresql+asyncpg dialect can be loaded."""
    try:
        import sqlalchemy

        sqlalchemy.engine.url.make_url("postgresql+asyncpg://u:p@h/db")._get_entrypoint()
        return True
    except Exception:
        return False


def test_create_engine_sqlite_async_translation():
    # Test that sqlite sync URL is translated to aiosqlite
    engine = _create_engine("sqlite:///test.db")
    assert str(engine.url).startswith("sqlite+aiosqlite:///")


@pytest.mark.skipif(
    not _asyncpg_dialect_available(),
    reason="postgresql+asyncpg dialect not available on this platform",
)
def test_create_engine_postgres_async_translation():
    engine = _create_engine("postgresql://user:pass@localhost/db")
    assert str(engine.url).startswith("postgresql+asyncpg://")


def test_create_engine_in_memory_sqlite():
    engine = _create_engine("sqlite:///:memory:")
    assert str(engine.url).startswith("sqlite+aiosqlite:///")
    # StaticPool should be used for in-memory sqlite
    from sqlalchemy.pool import StaticPool

    assert isinstance(engine.pool, StaticPool)

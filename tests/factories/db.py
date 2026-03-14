from sqlalchemy.ext.asyncio import AsyncEngine

from openviper.db.connection import configure_db, get_engine


async def create_test_engine(
    url: str = "sqlite+aiosqlite:///:memory:", echo: bool = False
) -> AsyncEngine:
    """Create and return a configured test database engine."""
    await configure_db(url, echo=echo)
    return await get_engine()

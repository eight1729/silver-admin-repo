
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

def _to_async_url(url: str) -> str:
    if url.startswith("postgresql+"):
        return url
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://") :]
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://") :]
    return url


_engine: AsyncEngine | None = None
_database_url: str | None = None


def configure_database_url(database_url: str) -> None:
    """Select the already-resolved database URL for the current process."""
    global _database_url
    if _engine is not None and _database_url != database_url:
        raise RuntimeError("database engine is already initialized")
    _database_url = database_url


def get_engine() -> AsyncEngine:
    global _database_url, _engine
    if _engine is None:
        if _database_url is None:
            # Compatibility path for the integrated legacy entrypoint only.
            from app.core.config import settings

            _database_url = settings.database_url
        _engine = create_async_engine(
            _to_async_url(_database_url),
            pool_pre_ping=True,
            pool_recycle=1800,
        )
    return _engine


def set_engine(engine: AsyncEngine | None) -> None:
    global _engine
    _engine = engine


async def dispose_engine() -> None:
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None


@asynccontextmanager
async def db_connection() -> AsyncGenerator[AsyncConnection, None]:
    engine = get_engine()
    async with engine.connect() as conn:
        yield conn

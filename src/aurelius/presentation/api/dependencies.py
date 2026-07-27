"""Dependency injection wiring.

All FastAPI route dependencies resolve here.
Single place to swap implementations (e.g., real DB → in-memory for tests).
"""

from collections.abc import AsyncGenerator
from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from aurelius.infrastructure.cache.redis import CacheManager
from aurelius.infrastructure.config.settings import Settings, get_settings
from aurelius.infrastructure.database.connection import DatabaseManager

# ── Singletons (created once per process) ────────────────────────────────────


@lru_cache(maxsize=1)
def get_database_manager(settings: Settings = Depends(get_settings)) -> DatabaseManager:
    return DatabaseManager(settings)


@lru_cache(maxsize=1)
def get_cache_manager(settings: Settings = Depends(get_settings)) -> CacheManager:
    return CacheManager(settings)


# ── Per-request dependencies ──────────────────────────────────────────────────


async def get_db_session(
    db: Annotated[DatabaseManager, Depends(get_database_manager)],
) -> AsyncGenerator[AsyncSession, None]:
    """Yield a transactional database session scoped to the request."""
    async with db.session() as session:
        yield session


# ── Type aliases for route signatures ────────────────────────────────────────

SettingsDep = Annotated[Settings, Depends(get_settings)]
DatabaseDep = Annotated[DatabaseManager, Depends(get_database_manager)]
CacheDep = Annotated[CacheManager, Depends(get_cache_manager)]
SessionDep = Annotated[AsyncSession, Depends(get_db_session)]

"""Dependency injection wiring.

All FastAPI route dependencies resolve here.
Single place to swap implementations (e.g., real DB → in-memory for tests).
"""

from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from mentisrex.infrastructure.cache.redis import CacheManager
from mentisrex.infrastructure.config.settings import Settings, get_settings
from mentisrex.infrastructure.database.connection import DatabaseManager

# ── Singletons (created once per process) ────────────────────────────────────
# lru_cache cannot be used here: FastAPI Depends() markers are not hashable and
# the cache key would collapse across different settings instances. Use module-
# level singletons initialized lazily instead.

_db_manager: DatabaseManager | None = None
_cache_manager: CacheManager | None = None


def get_database_manager(settings: Annotated[Settings, Depends(get_settings)]) -> DatabaseManager:
    global _db_manager
    if _db_manager is None:
        _db_manager = DatabaseManager(settings)
    return _db_manager


def get_cache_manager(settings: Annotated[Settings, Depends(get_settings)]) -> CacheManager:
    global _cache_manager
    if _cache_manager is None:
        _cache_manager = CacheManager(settings)
    return _cache_manager


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

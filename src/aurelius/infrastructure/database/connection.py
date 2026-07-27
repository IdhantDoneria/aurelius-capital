"""Async SQLAlchemy engine and session factory.

One engine per process. Sessions are created per-request via FastAPI dependency.
Never import the engine directly in business logic — use the session dependency.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from aurelius.core.errors import DatabaseError
from aurelius.core.logging import get_logger
from aurelius.infrastructure.config.settings import Settings

logger = get_logger(__name__)


class Base(DeclarativeBase):
    """SQLAlchemy declarative base. All ORM models inherit from this."""

    pass


class DatabaseManager:
    """Manages engine lifecycle and session creation."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._engine: AsyncEngine | None = None
        self._session_factory: async_sessionmaker[AsyncSession] | None = None

    def init(self) -> None:
        """Create engine and session factory. Call at application startup."""
        self._engine = create_async_engine(
            self._settings.database_url,
            pool_size=self._settings.database_pool_size,
            max_overflow=self._settings.database_max_overflow,
            pool_pre_ping=True,  # validate connections before using
            echo=self._settings.app_debug,
        )
        self._session_factory = async_sessionmaker(
            self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        logger.info(
            "database_initialized",
            host=self._settings.database_host,
            database=self._settings.database_name,
        )

    async def close(self) -> None:
        """Dispose engine. Call at application shutdown."""
        if self._engine:
            await self._engine.dispose()
            logger.info("database_connection_closed")

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession, None]:
        """Context manager yielding a transactional session."""
        if self._session_factory is None:
            raise DatabaseError("Database not initialized. Call init() first.")

        async with self._session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def check_connection(self) -> bool:
        """Return True if database is reachable. Used by health check."""
        if self._engine is None:
            return False
        try:
            async with self._engine.connect() as conn:
                await conn.execute(__import__("sqlalchemy").text("SELECT 1"))
            return True
        except Exception as exc:
            logger.warning("database_health_check_failed", error=str(exc))
            return False

"""Redis client wrapper.

Thin abstraction over redis-py async client.
Centralizes connection management and error translation.
"""

import json
from typing import Any

import redis.asyncio as aioredis
from redis.asyncio import Redis
from redis.exceptions import RedisError

from aurelius.core.errors import CacheError
from aurelius.core.logging import get_logger
from aurelius.infrastructure.config.settings import Settings

logger = get_logger(__name__)


class CacheManager:
    """Manages Redis connection lifecycle."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: Redis | None = None  # type: ignore[type-arg]

    def init(self) -> None:
        """Create Redis connection pool. Call at application startup."""
        self._client = aioredis.from_url(
            self._settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
        logger.info(
            "cache_initialized",
            host=self._settings.redis_host,
            db=self._settings.redis_db,
        )

    async def close(self) -> None:
        """Close connection pool. Call at application shutdown."""
        if self._client:
            await self._client.aclose()
            logger.info("cache_connection_closed")

    def _require_client(self) -> Redis:  # type: ignore[type-arg]
        if self._client is None:
            raise CacheError("Cache not initialized. Call init() first.")
        return self._client

    async def get(self, key: str) -> Any | None:
        """Return deserialized value or None if key missing."""
        try:
            raw = await self._require_client().get(key)
            return json.loads(raw) if raw is not None else None
        except RedisError as exc:
            raise CacheError(f"Cache get failed for key '{key}'", detail=str(exc)) from exc

    async def set(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        """Serialize and store value. Optional TTL in seconds."""
        try:
            serialized = json.dumps(value, default=str)
            await self._require_client().set(key, serialized, ex=ttl_seconds)
        except RedisError as exc:
            raise CacheError(f"Cache set failed for key '{key}'", detail=str(exc)) from exc

    async def delete(self, *keys: str) -> int:
        """Delete one or more keys. Returns count deleted."""
        try:
            return await self._require_client().delete(*keys)
        except RedisError as exc:
            raise CacheError(f"Cache delete failed for keys {keys}", detail=str(exc)) from exc

    async def exists(self, key: str) -> bool:
        try:
            return bool(await self._require_client().exists(key))
        except RedisError as exc:
            raise CacheError(f"Cache exists check failed for key '{key}'", detail=str(exc)) from exc

    async def check_connection(self) -> bool:
        """Return True if Redis is reachable. Used by health check."""
        try:
            return bool(await self._require_client().ping())
        except Exception as exc:
            logger.warning("cache_health_check_failed", error=type(exc).__name__)
            return False

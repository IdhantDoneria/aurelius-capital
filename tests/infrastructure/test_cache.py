"""Tests for CacheManager — fully mocked Redis, no real connection required.

Module at 40% coverage: init, get, set, delete, exists, check_connection,
and error paths (RedisError → CacheError) all untested.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aurelius.core.errors import CacheError
from aurelius.infrastructure.cache.redis import CacheManager


def _settings(url: str = "redis://localhost:6380/0") -> MagicMock:
    s = MagicMock()
    s.redis_url = url
    s.redis_host = "localhost"
    s.redis_db = 0
    return s


def _manager_with_mock_client() -> tuple[CacheManager, AsyncMock]:
    """Return (manager, mock_redis_client). Manager has mock client pre-injected."""
    mgr = CacheManager(_settings())
    client = AsyncMock()
    mgr._client = client
    return mgr, client


# ── init ──────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_require_client_raises_before_init():
    mgr = CacheManager(_settings())
    with pytest.raises(CacheError, match="not initialized"):
        mgr._require_client()


@pytest.mark.unit
def test_init_creates_client():
    mgr = CacheManager(_settings())
    with patch("aurelius.infrastructure.cache.redis.aioredis.from_url") as mock_from_url:
        mock_from_url.return_value = AsyncMock()
        mgr.init()
        mock_from_url.assert_called_once()
        assert mgr._client is not None


# ── close ──────────────────────────────────────────────────────────────────────


@pytest.mark.unit
async def test_close_calls_aclose():
    mgr, client = _manager_with_mock_client()
    await mgr.close()
    client.aclose.assert_awaited_once()


@pytest.mark.unit
async def test_close_without_init_is_safe():
    mgr = CacheManager(_settings())
    await mgr.close()  # should not raise


# ── get ────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
async def test_get_returns_deserialized_value():
    mgr, client = _manager_with_mock_client()
    client.get.return_value = '{"score": 42}'
    result = await mgr.get("my_key")
    assert result == {"score": 42}
    client.get.assert_awaited_once_with("my_key")


@pytest.mark.unit
async def test_get_returns_none_for_missing_key():
    mgr, client = _manager_with_mock_client()
    client.get.return_value = None
    assert await mgr.get("missing") is None


@pytest.mark.unit
async def test_get_redis_error_raises_cache_error():
    mgr, client = _manager_with_mock_client()
    from redis.exceptions import RedisError
    client.get.side_effect = RedisError("connection lost")
    with pytest.raises(CacheError, match="Cache get failed"):
        await mgr.get("key")


# ── set ────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
async def test_set_serializes_and_stores():
    mgr, client = _manager_with_mock_client()
    await mgr.set("k", {"v": 1})
    client.set.assert_awaited_once()
    args = client.set.call_args
    assert args[0][0] == "k"  # key
    assert '"v": 1' in args[0][1]  # serialized JSON


@pytest.mark.unit
async def test_set_with_ttl_passes_ex():
    mgr, client = _manager_with_mock_client()
    await mgr.set("k", "val", ttl_seconds=60)
    _, kwargs = client.set.call_args
    assert kwargs.get("ex") == 60


@pytest.mark.unit
async def test_set_redis_error_raises_cache_error():
    mgr, client = _manager_with_mock_client()
    from redis.exceptions import RedisError
    client.set.side_effect = RedisError("oom")
    with pytest.raises(CacheError, match="Cache set failed"):
        await mgr.set("k", "v")


# ── delete ────────────────────────────────────────────────────────────────────


@pytest.mark.unit
async def test_delete_returns_count():
    mgr, client = _manager_with_mock_client()
    client.delete.return_value = 2
    count = await mgr.delete("k1", "k2")
    assert count == 2
    client.delete.assert_awaited_once_with("k1", "k2")


@pytest.mark.unit
async def test_delete_redis_error_raises_cache_error():
    mgr, client = _manager_with_mock_client()
    from redis.exceptions import RedisError
    client.delete.side_effect = RedisError("dead")
    with pytest.raises(CacheError, match="Cache delete failed"):
        await mgr.delete("k")


# ── exists ─────────────────────────────────────────────────────────────────────


@pytest.mark.unit
async def test_exists_true_when_key_present():
    mgr, client = _manager_with_mock_client()
    client.exists.return_value = 1
    assert await mgr.exists("k") is True


@pytest.mark.unit
async def test_exists_false_when_missing():
    mgr, client = _manager_with_mock_client()
    client.exists.return_value = 0
    assert await mgr.exists("k") is False


@pytest.mark.unit
async def test_exists_redis_error_raises_cache_error():
    mgr, client = _manager_with_mock_client()
    from redis.exceptions import RedisError
    client.exists.side_effect = RedisError("err")
    with pytest.raises(CacheError, match="Cache exists check failed"):
        await mgr.exists("k")


# ── check_connection ───────────────────────────────────────────────────────────


@pytest.mark.unit
async def test_check_connection_returns_true_on_pong():
    mgr, client = _manager_with_mock_client()
    client.ping.return_value = True
    assert await mgr.check_connection() is True


@pytest.mark.unit
async def test_check_connection_returns_false_on_error():
    mgr, client = _manager_with_mock_client()
    client.ping.side_effect = Exception("refused")
    assert await mgr.check_connection() is False

"""Pytest configuration and shared fixtures.

Fixtures marked 'unit' need no external services.
Fixtures marked 'integration' require the test Docker stack.
"""

import os
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

# Point settings at test environment before any imports load the singleton
os.environ.setdefault("ENVIRONMENT", "testing")
os.environ.setdefault("DATABASE_HOST", "localhost")
os.environ.setdefault("DATABASE_PORT", "5433")
os.environ.setdefault("DATABASE_NAME", "aurelius_test")
os.environ.setdefault("DATABASE_USER", "aurelius")
os.environ.setdefault("DATABASE_PASSWORD", "test_password")
os.environ.setdefault("REDIS_HOST", "localhost")
os.environ.setdefault("REDIS_PORT", "6380")
os.environ.setdefault("SECRET_KEY", "test-secret-key-long-enough")


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


# ── Unit test fixtures (no I/O) ────────────────────────────────────────────────


@pytest.fixture
def mock_db_manager() -> AsyncMock:
    manager = AsyncMock()
    manager.check_connection.return_value = True
    return manager


@pytest.fixture
def mock_cache_manager() -> AsyncMock:
    manager = AsyncMock()
    manager.check_connection.return_value = True
    return manager


@pytest.fixture
def app_with_mocks(mock_db_manager: AsyncMock, mock_cache_manager: AsyncMock) -> FastAPI:
    """FastAPI app with infrastructure dependencies replaced by mocks."""
    from aurelius.main import create_app
    from aurelius.presentation.api.dependencies import get_cache_manager, get_database_manager

    application = create_app()
    application.dependency_overrides[get_database_manager] = lambda: mock_db_manager
    application.dependency_overrides[get_cache_manager] = lambda: mock_cache_manager
    return application


@pytest_asyncio.fixture
async def client(app_with_mocks: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    """Async HTTP client wired to the app with mocked dependencies."""
    async with AsyncClient(
        transport=ASGITransport(app=app_with_mocks),
        base_url="http://test",
    ) as c:
        yield c

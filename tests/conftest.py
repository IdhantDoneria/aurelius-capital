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
os.environ.setdefault("DATABASE_NAME", "mentisrex_test")
os.environ.setdefault("DATABASE_USER", "mentisrex")
os.environ.setdefault("DATABASE_PASSWORD", "test_password")
os.environ.setdefault("REDIS_HOST", "localhost")
os.environ.setdefault("REDIS_PORT", "6380")
os.environ.setdefault("SECRET_KEY", "test-secret-key-long-enough")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Structurally skip real-network tests, independent of any -m flag.

    pyproject.toml's addopts also excludes real_alpaca/real_data by default,
    but that alone is not robust: pytest's `-m` is a single-value option, so
    any invocation that passes its own `-m` (CI's unit-tests job runs
    `pytest tests/ -m "not integration"`) silently replaces addopts' filter
    rather than combining with it, re-admitting these tests.

    Gated on an explicit opt-in env var rather than credential presence:
    a developer who happens to have ALPACA_PAPER_API_KEY exported in their
    shell for unrelated reasons should not have a routine `pytest -q` start
    hitting a live account. Set MRX_RUN_LIVE_TESTS=1 to actually run these
    (the tests' own internal checks, e.g. a missing-credential pytest.skip
    or a failed account-verification call, still apply on top of this).
    """
    if os.environ.get("MRX_RUN_LIVE_TESTS") == "1":
        return
    skip_alpaca = pytest.mark.skip(
        reason="real_alpaca requires MRX_RUN_LIVE_TESTS=1 plus "
        "ALPACA_PAPER_API_KEY/ALPACA_PAPER_API_SECRET"
    )
    skip_data = pytest.mark.skip(
        reason="real_data requires MRX_RUN_LIVE_TESTS=1 and live network access"
    )
    for item in items:
        if "real_alpaca" in item.keywords:
            item.add_marker(skip_alpaca)
        if "real_data" in item.keywords:
            item.add_marker(skip_data)


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
    from mentisrex.main import create_app
    from mentisrex.presentation.api.dependencies import get_cache_manager, get_database_manager

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

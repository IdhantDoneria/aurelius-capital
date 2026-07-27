"""Integration tests for health endpoints.

Uses mocked infrastructure — tests HTTP contract only.
Full DB/Redis connectivity tested by the readiness endpoint path.
"""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_liveness_returns_200(client: AsyncClient) -> None:
    response = await client.get("/health/live")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_liveness_response_schema(client: AsyncClient) -> None:
    response = await client.get("/health/live")
    data = response.json()
    assert data["status"] == "ok"
    assert "timestamp" in data
    assert "environment" in data
    assert "version" in data


@pytest.mark.asyncio
async def test_liveness_includes_request_id_header(client: AsyncClient) -> None:
    response = await client.get("/health/live")
    assert "X-Request-ID" in response.headers


@pytest.mark.asyncio
async def test_readiness_with_healthy_deps_returns_200(client: AsyncClient) -> None:
    response = await client.get("/health/ready")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_readiness_response_schema(client: AsyncClient) -> None:
    response = await client.get("/health/ready")
    data = response.json()
    assert "status" in data
    assert "dependencies" in data
    assert "database" in data["dependencies"]
    assert "cache" in data["dependencies"]


@pytest.mark.asyncio
async def test_readiness_reports_ready_when_all_deps_ok(client: AsyncClient) -> None:
    response = await client.get("/health/ready")
    data = response.json()
    assert data["status"] == "ready"
    assert data["dependencies"]["database"]["status"] == "ok"
    assert data["dependencies"]["cache"]["status"] == "ok"

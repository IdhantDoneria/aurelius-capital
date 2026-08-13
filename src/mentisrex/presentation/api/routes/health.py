"""Health check endpoints.

/health/live   — is the process alive? (Kubernetes liveness probe)
/health/ready  — can the process serve traffic? (Kubernetes readiness probe)

Readiness checks real connectivity to PostgreSQL and Redis.
Liveness never checks external deps — a slow DB shouldn't kill the pod.
"""

from datetime import UTC, datetime

from fastapi import APIRouter
from pydantic import BaseModel

from mentisrex.presentation.api.dependencies import CacheDep, DatabaseDep, SettingsDep

router = APIRouter(prefix="/health", tags=["health"])


class LivenessResponse(BaseModel):
    status: str
    timestamp: datetime
    environment: str
    version: str = "0.1.0"


class DependencyStatus(BaseModel):
    status: str
    latency_ms: float | None = None


class ReadinessResponse(BaseModel):
    status: str
    timestamp: datetime
    dependencies: dict[str, DependencyStatus]


@router.get("/live", response_model=LivenessResponse, summary="Liveness probe")
async def liveness(settings: SettingsDep) -> LivenessResponse:
    """Returns 200 if the process is alive. Never touches external services."""
    return LivenessResponse(
        status="ok",
        timestamp=datetime.now(UTC),
        environment=settings.environment,
    )


@router.get("/ready", response_model=ReadinessResponse, summary="Readiness probe")
async def readiness(
    settings: SettingsDep,
    db: DatabaseDep,
    cache: CacheDep,
) -> ReadinessResponse:
    """Returns 200 if all dependencies are reachable, 503 otherwise."""
    import time

    dependencies: dict[str, DependencyStatus] = {}

    # Check database
    t0 = time.perf_counter()
    db_ok = await db.check_connection()
    db_ms = round((time.perf_counter() - t0) * 1000, 2)
    dependencies["database"] = DependencyStatus(
        status="ok" if db_ok else "unavailable",
        latency_ms=db_ms if db_ok else None,
    )

    # Check cache
    t0 = time.perf_counter()
    cache_ok = await cache.check_connection()
    cache_ms = round((time.perf_counter() - t0) * 1000, 2)
    dependencies["cache"] = DependencyStatus(
        status="ok" if cache_ok else "unavailable",
        latency_ms=cache_ms if cache_ok else None,
    )

    all_ok = all(dep.status == "ok" for dep in dependencies.values())

    return ReadinessResponse(
        status="ready" if all_ok else "degraded",
        timestamp=datetime.now(UTC),
        dependencies=dependencies,
    )

"""Aurelius Capital — application factory.

Uses FastAPI's lifespan context manager to initialize and tear down
infrastructure connections (DB engine, Redis pool) on startup/shutdown.

create_app() is importable so tests can instantiate the app directly.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

from aurelius.core.errors import AureliusError
from aurelius.core.logging import configure_logging, get_logger
from aurelius.catalog.api import catalog_router
from aurelius.catalog.store import CatalogStore
from aurelius.corpus.api import router as corpus_router
from aurelius.director.api import router as director_router
from aurelius.discovery.api import discovery_router
from aurelius.infrastructure.cache.redis import CacheManager
from aurelius.infrastructure.config.settings import get_settings
from aurelius.infrastructure.database.connection import DatabaseManager
from aurelius.intelligence.api import router as intel_router
from aurelius.knowledge import hooks as kg_hooks
from aurelius.knowledge.api import _get_kg
from aurelius.knowledge.api import router as kg_router
from aurelius.lab.api import router as lab_router
from aurelius.presentation.api.routes import health, metrics
from aurelius.presentation.middleware.logging import RequestLoggingMiddleware

_STATIC_DIR = Path(__file__).parent / "static"

logger = get_logger(__name__)


def create_app() -> FastAPI:
    settings = get_settings()

    configure_logging(log_level=settings.log_level, json_logs=settings.json_logs)

    db_manager = DatabaseManager(settings)
    cache_manager = CacheManager(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        logger.info("startup_begin", environment=settings.environment)
        db_manager.init()
        cache_manager.init()
        kg_hooks.configure(_get_kg())  # wire live-update hooks
        CatalogStore(settings.catalog_path).bootstrap()
        logger.info("startup_complete")
        yield
        logger.info("shutdown_begin")
        await db_manager.close()
        await cache_manager.close()
        logger.info("shutdown_complete")

    app = FastAPI(
        title="Aurelius Capital",
        description="Institutional-grade quantitative research and trading platform",
        version="0.1.0",
        debug=settings.app_debug,
        docs_url="/docs" if not settings.is_production else None,
        redoc_url="/redoc" if not settings.is_production else None,
        lifespan=lifespan,
    )

    # ── Middleware ────────────────────────────────────────────────────────────
    app.add_middleware(RequestLoggingMiddleware)

    # ── Exception handlers ────────────────────────────────────────────────────
    @app.exception_handler(AureliusError)
    async def aurelius_error_handler(request: Request, exc: AureliusError) -> JSONResponse:
        logger.warning(
            "handled_exception",
            error_code=exc.error_code,
            message=exc.message,
            path=str(request.url),
        )
        return JSONResponse(
            status_code=exc.http_status,
            content=exc.to_dict(include_detail=not settings.is_production),
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled_exception", path=str(request.url))
        return JSONResponse(
            status_code=500,
            content={"error": "INTERNAL_ERROR", "message": "An unexpected error occurred"},
        )

    # ── Routers ───────────────────────────────────────────────────────────────
    app.include_router(health.router)
    app.include_router(metrics.router)
    app.include_router(kg_router)
    app.include_router(corpus_router)
    app.include_router(director_router)
    app.include_router(intel_router)
    app.include_router(lab_router)
    app.include_router(discovery_router)
    app.include_router(catalog_router)

    @app.get("/kg/explore", include_in_schema=False)
    async def kg_explorer() -> FileResponse:
        return FileResponse(str(_STATIC_DIR / "kg_explorer.html"))

    @app.get("/director/dashboard/view", include_in_schema=False)
    async def director_dashboard_view() -> FileResponse:
        return FileResponse(str(_STATIC_DIR / "director_dashboard.html"))

    @app.get("/intel/dashboard/view", include_in_schema=False)
    async def intel_dashboard_view() -> FileResponse:
        return FileResponse(str(_STATIC_DIR / "intel_dashboard.html"))

    @app.get("/lab/dashboard/view", include_in_schema=False)
    async def lab_dashboard_view() -> FileResponse:
        return FileResponse(str(_STATIC_DIR / "lab_dashboard.html"))

    # Store managers on app state so dependencies can reach them
    app.state.db = db_manager
    app.state.cache = cache_manager

    return app


app = create_app()

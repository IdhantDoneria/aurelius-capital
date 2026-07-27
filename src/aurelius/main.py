"""Aurelius Capital — application factory.

Uses FastAPI's lifespan context manager to initialize and tear down
infrastructure connections (DB engine, Redis pool) on startup/shutdown.

create_app() is importable so tests can instantiate the app directly.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from aurelius.core.errors import AureliusError
from aurelius.core.logging import configure_logging, get_logger
from aurelius.infrastructure.cache.redis import CacheManager
from aurelius.infrastructure.config.settings import get_settings
from aurelius.infrastructure.database.connection import DatabaseManager
from aurelius.presentation.api.routes import health, metrics
from aurelius.presentation.middleware.logging import RequestLoggingMiddleware

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

    # Store managers on app state so dependencies can reach them
    app.state.db = db_manager
    app.state.cache = cache_manager

    return app


app = create_app()

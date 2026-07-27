"""Exception hierarchy for Aurelius Capital.

All custom exceptions inherit from AureliusError.
FastAPI exception handlers map these to HTTP responses.
Stack traces never leak to API clients in production.
"""

from http import HTTPStatus


class AureliusError(Exception):
    """Root exception. All platform errors inherit from this."""

    http_status: int = HTTPStatus.INTERNAL_SERVER_ERROR
    error_code: str = "INTERNAL_ERROR"

    def __init__(self, message: str, detail: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail

    def to_dict(self, include_detail: bool = False) -> dict[str, str]:
        payload: dict[str, str] = {
            "error": self.error_code,
            "message": self.message,
        }
        if include_detail and self.detail:
            payload["detail"] = self.detail
        return payload


# ── Configuration errors ───────────────────────────────────────────────────────


class ConfigurationError(AureliusError):
    """Raised when required configuration is missing or invalid."""

    http_status = HTTPStatus.INTERNAL_SERVER_ERROR
    error_code = "CONFIGURATION_ERROR"


# ── Infrastructure errors ──────────────────────────────────────────────────────


class InfrastructureError(AureliusError):
    """Base for all infrastructure-layer errors (DB, cache, network)."""

    http_status = HTTPStatus.SERVICE_UNAVAILABLE
    error_code = "INFRASTRUCTURE_ERROR"


class DatabaseError(InfrastructureError):
    """PostgreSQL / SQLAlchemy errors."""

    error_code = "DATABASE_ERROR"


class CacheError(InfrastructureError):
    """Redis errors."""

    error_code = "CACHE_ERROR"


class ConnectionError(InfrastructureError):
    """Cannot connect to a required service."""

    error_code = "CONNECTION_ERROR"


# ── Domain errors ──────────────────────────────────────────────────────────────


class DomainError(AureliusError):
    """Business rule violations."""

    http_status = HTTPStatus.UNPROCESSABLE_ENTITY
    error_code = "DOMAIN_ERROR"


class ValidationError(DomainError):
    """Invalid input to a domain entity or value object."""

    http_status = HTTPStatus.BAD_REQUEST
    error_code = "VALIDATION_ERROR"


class NotFoundError(DomainError):
    """Requested resource does not exist."""

    http_status = HTTPStatus.NOT_FOUND
    error_code = "NOT_FOUND"


class ConflictError(DomainError):
    """Resource already exists or state conflict."""

    http_status = HTTPStatus.CONFLICT
    error_code = "CONFLICT"


# ── Market data errors ─────────────────────────────────────────────────────────


class MarketDataError(DomainError):
    """Market data quality or availability issues."""

    error_code = "MARKET_DATA_ERROR"


class StaleDataError(MarketDataError):
    """Data is older than the acceptable staleness threshold."""

    error_code = "STALE_DATA"


class BadTickError(MarketDataError):
    """Tick data failed quality checks."""

    error_code = "BAD_TICK"

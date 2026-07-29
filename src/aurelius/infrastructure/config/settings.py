"""Application configuration via pydantic-settings.

Reads from environment variables. .env files loaded by the application
entrypoint, not here — this class only reads what's already in the env.

Validation runs at import time. Bad config = hard crash at startup.
"""

from enum import StrEnum
from functools import lru_cache

from pydantic import Field, computed_field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    DEVELOPMENT = "development"
    TESTING = "testing"
    PRODUCTION = "production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env.development",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Runtime ───────────────────────────────────────────────────────────────
    environment: Environment = Environment.DEVELOPMENT
    app_host: str = "0.0.0.0"
    app_port: int = Field(default=8000, ge=1, le=65535)
    app_debug: bool = False
    log_level: str = "INFO"
    secret_key: str = Field(default="insecure-dev-key", min_length=12)

    # ── Database ──────────────────────────────────────────────────────────────
    database_host: str = "localhost"
    database_port: int = Field(default=5432, ge=1, le=65535)
    database_name: str = "aurelius_dev"
    database_user: str = "aurelius"
    database_password: str = "change_me"
    database_pool_size: int = Field(default=10, ge=1, le=100)
    database_max_overflow: int = Field(default=20, ge=0, le=100)

    # ── Redis ─────────────────────────────────────────────────────────────────
    redis_host: str = "localhost"
    redis_port: int = Field(default=6379, ge=1, le=65535)
    redis_db: int = Field(default=0, ge=0, le=15)
    redis_password: str = ""

    # ── Alpaca Markets ────────────────────────────────────────────────────────
    alpaca_api_key: str = ""
    alpaca_api_secret: str = ""

    # ── DuckDB analytical store ───────────────────────────────────────────────
    duckdb_path: str = "./data/analytics.duckdb"
    knowledge_graph_path: str = "./data/knowledge_graph.duckdb"
    paper_outcomes_path: str = "./data/paper_outcomes.duckdb"
    corpus_path: str = "./data/corpus.duckdb"
    catalog_path: str = "./data/catalog.duckdb"

    # ── Computed ──────────────────────────────────────────────────────────────
    @computed_field  # type: ignore[prop-decorator]
    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.database_user}:{self.database_password}"
            f"@{self.database_host}:{self.database_port}/{self.database_name}"
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def database_url_sync(self) -> str:
        """Sync URL for Alembic migrations."""
        return (
            f"postgresql+psycopg2://{self.database_user}:{self.database_password}"
            f"@{self.database_host}:{self.database_port}/{self.database_name}"
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def redis_url(self) -> str:
        if self.redis_password:
            return f"redis://:{self.redis_password}@{self.redis_host}:{self.redis_port}/{self.redis_db}"
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"

    # ── Derived flags ─────────────────────────────────────────────────────────
    @property
    def is_production(self) -> bool:
        return self.environment == Environment.PRODUCTION

    @property
    def json_logs(self) -> bool:
        return self.environment != Environment.DEVELOPMENT

    @model_validator(mode="after")
    def production_safety_checks(self) -> "Settings":
        if self.is_production and self.secret_key == "insecure-dev-key":
            raise ValueError("SECRET_KEY must be set to a secure value in production")
        if self.is_production and self.app_debug:
            raise ValueError("APP_DEBUG must be false in production")
        if self.is_production and self.database_password in ("change_me", ""):
            raise ValueError("DATABASE_PASSWORD must be set to a secure value in production")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached singleton. Import and call this everywhere."""
    return Settings()

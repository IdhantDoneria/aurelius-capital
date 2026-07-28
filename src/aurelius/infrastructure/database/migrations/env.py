"""Alembic environment configuration.

Supports both sync (alembic upgrade head) and async (application startup) modes.
The sync path uses psycopg2 — required by Alembic's migration runner.
The async path uses asyncpg — used by the FastAPI application.
"""

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlalchemy.engine import Connection

from aurelius.infrastructure.database.models import (  # noqa: F401
    fundamental,
    market,
    reference,
    research,
    trading,
)

# Import all models so their metadata is registered on Base
from aurelius.infrastructure.database.models.base import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_url() -> str:
    """Build sync database URL from environment. Alembic uses psycopg2."""
    host = os.environ.get("DATABASE_HOST", "localhost")
    port = os.environ.get("DATABASE_PORT", "5432")
    name = os.environ.get("DATABASE_NAME", "aurelius_dev")
    user = os.environ.get("DATABASE_USER", "aurelius")
    password = os.environ.get("DATABASE_PASSWORD")
    if not password:
        raise RuntimeError(
            "DATABASE_PASSWORD env var is not set. "
            "Set it before running Alembic migrations."
        )
    return f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{name}"


def run_migrations_offline() -> None:
    """Generate SQL script without a live DB connection."""
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations with a live sync connection."""
    connectable = engine_from_config(
        {"sqlalchemy.url": get_url()},
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        do_run_migrations(connection)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

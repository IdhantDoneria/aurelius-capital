"""Integration test for migration 0002 — OHLCV DEFAULT partition.

Proves the historical-depth cap is gone: after migrations, `market_data_ohlcv`
has a DEFAULT partition, so a bar dated outside the declared 2020-2026 monthly
partitions no longer errors on insert. Also asserts the declared monthly
partitions still exist (partition pruning preserved for the hot window).

Requires the test Docker stack (Postgres on the configured host/port) with
migrations applied (`alembic upgrade head`). Skips cleanly if the DB is
unreachable. Read-only: the functional insert runs inside a rolled-back
transaction.
"""

from __future__ import annotations

import os

import pytest

asyncpg = pytest.importorskip("asyncpg")


def _dsn() -> str:
    return (
        f"postgresql://{os.environ['DATABASE_USER']}:{os.environ['DATABASE_PASSWORD']}"
        f"@{os.environ['DATABASE_HOST']}:{os.environ['DATABASE_PORT']}"
        f"/{os.environ['DATABASE_NAME']}"
    )


async def _connect():
    try:
        return await asyncpg.connect(_dsn(), timeout=3)
    except (OSError, asyncpg.PostgresError) as exc:  # DB not running in this env
        pytest.skip(f"test Postgres unavailable: {exc}")


_PARTITION_BOUNDS = """
    SELECT c.relname AS name, pg_get_expr(c.relpartbound, c.oid) AS bound
    FROM pg_inherits i
    JOIN pg_class c ON c.oid = i.inhrelid
    JOIN pg_class p ON p.oid = i.inhparent
    WHERE p.relname = 'market_data_ohlcv'
"""


@pytest.mark.integration
async def test_default_partition_attached():
    """The DEFAULT partition exists — arbitrary dates have somewhere to land."""
    conn = await _connect()
    try:
        rows = await conn.fetch(_PARTITION_BOUNDS)
    finally:
        await conn.close()

    by_name = {r["name"]: r["bound"] for r in rows}
    assert "market_data_ohlcv_default" in by_name, "migration 0002 default partition missing"
    assert by_name["market_data_ohlcv_default"] == "DEFAULT"
    # Hot-window declared partitions still present → pruning preserved.
    assert "market_data_ohlcv_y2020m01" in by_name
    assert by_name["market_data_ohlcv_y2020m01"] != "DEFAULT"


@pytest.mark.integration
async def test_out_of_window_date_inserts_without_error():
    """A pre-2020 bar (previously rejected: 'no partition found') now inserts and
    routes to the default partition. Runs in a rolled-back transaction."""
    conn = await _connect()
    try:
        tx = conn.transaction()
        await tx.start()
        try:
            source_id = await conn.fetchval(
                "INSERT INTO data_sources (name, source_type) "
                "VALUES ('pt_test_src', 'csv') RETURNING id"
            )
            symbol_id = await conn.fetchval(
                "INSERT INTO symbols (ticker, asset_class) "
                "VALUES ('PTEST', 'equity') RETURNING id"
            )
            # 1990 is far outside the declared 2020-2026 partitions.
            await conn.execute(
                """
                INSERT INTO market_data_ohlcv
                    (symbol_id, source_id, timestamp, frequency,
                     open, high, low, close, volume, quality_score)
                VALUES ($1, $2, '1990-06-15T00:00:00Z', '1d',
                        10, 11, 9, 10.5, 1000, 100)
                """,
                symbol_id,
                source_id,
            )
            landed = await conn.fetchval(
                "SELECT tableoid::regclass::text FROM market_data_ohlcv "
                "WHERE symbol_id = $1",
                symbol_id,
            )
            assert landed == "market_data_ohlcv_default"
        finally:
            await tx.rollback()
    finally:
        await conn.close()

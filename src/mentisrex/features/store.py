"""Feature store — the durable layer between pipeline and strategies.

DuckDB-backed, mirroring `market_data.storage.DuckDBStore`: PostgreSQL
(`research.FeatureDefinition` / `FeatureValue`) is the authoritative record;
this is the research-speed replica strategies read from.

Two tables:
  feature_definitions — one row per feature version (the registry, persisted).
  feature_values      — (symbol, feature, version, timestamp) → value.

Point-in-time correctness on read: `read_values(as_of=...)` and
`cross_section(...)` only return rows with timestamp <= as_of, so a strategy
querying "as of date T" can never pull a value computed after T.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path

import duckdb

from mentisrex.core.logging import get_logger
from mentisrex.features.pipeline import FeatureValueRow
from mentisrex.features.registry import Feature, to_definition_row

logger = get_logger(__name__)

_CREATE_DEFS = """
CREATE TABLE IF NOT EXISTS feature_definitions (
    name                VARCHAR      NOT NULL,
    version             SMALLINT     NOT NULL,
    category            VARCHAR      NOT NULL,
    description         VARCHAR,
    formula             VARCHAR,
    inputs              VARCHAR,
    min_periods         INTEGER,
    frequency           VARCHAR,
    owner               VARCHAR,
    status              VARCHAR,
    economic_intuition  VARCHAR,
    expected_behavior   VARCHAR,
    failure_modes       VARCHAR,
    validation_method   VARCHAR,
    PRIMARY KEY (name, version)
)
"""

_CREATE_VALUES = """
CREATE TABLE IF NOT EXISTS feature_values (
    symbol     VARCHAR      NOT NULL,
    feature    VARCHAR      NOT NULL,
    version    SMALLINT     NOT NULL,
    timestamp  TIMESTAMPTZ  NOT NULL,
    value      DECIMAL(28,8),
    PRIMARY KEY (symbol, feature, version, timestamp)
)
"""


class FeatureStore:
    def __init__(self, db_path: str = "./data/features.duckdb") -> None:
        self._path = db_path
        self._in_memory = db_path == ":memory:"
        self._persistent_conn: duckdb.DuckDBPyConnection | None = None

        if not self._in_memory:
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        else:
            self._persistent_conn = duckdb.connect(":memory:")

        with self._conn() as conn:
            conn.execute(_CREATE_DEFS)
            conn.execute(_CREATE_VALUES)

    @contextmanager
    def _conn(self) -> Generator[duckdb.DuckDBPyConnection, None, None]:
        if self._in_memory and self._persistent_conn is not None:
            yield self._persistent_conn
        else:
            conn = duckdb.connect(self._path)
            try:
                yield conn
            finally:
                conn.close()

    def close(self) -> None:
        if self._persistent_conn:
            self._persistent_conn.close()
            self._persistent_conn = None

    def sync_definitions(self, features: list[Feature]) -> int:
        """Upsert feature specs. Call after registering/changing features."""
        rows = []
        for f in features:
            d = to_definition_row(f)
            cfg = d["computation_config"]
            rows.append(
                (
                    d["name"],
                    d["version"],
                    d["category"],
                    d["description"],
                    cfg["formula"],
                    ",".join(cfg["inputs"]),
                    cfg["min_periods"],
                    cfg["frequency"],
                    d["owner"],
                    d["status"],
                    d["economic_intuition"],
                    d["expected_behavior"],
                    d["failure_modes"],
                    d["validation_method"],
                )
            )
        with self._conn() as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO feature_definitions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                rows,
            )
        logger.info("feature_defs_synced", count=len(rows))
        return len(rows)

    def write_values(self, rows: list[FeatureValueRow]) -> int:
        """Persist computed values. None values are skipped (nothing to store)."""
        payload = [
            (r.symbol, r.feature, r.version, r.timestamp, r.value)
            for r in rows
            if r.value is not None
        ]
        if not payload:
            return 0
        with self._conn() as conn:
            conn.executemany("INSERT OR REPLACE INTO feature_values VALUES (?,?,?,?,?)", payload)
        logger.info("feature_values_written", count=len(payload))
        return len(payload)

    def read_values(
        self,
        symbol: str,
        feature: str,
        version: int | None = None,
        as_of: date | datetime | None = None,
    ) -> list[dict]:
        """Values for one symbol+feature, ascending. `as_of` clips the future."""
        sql = (
            "SELECT symbol, feature, version, timestamp, value"
            " FROM feature_values WHERE symbol = ? AND feature = ?"
        )
        params: list = [symbol, feature]
        if version is not None:
            sql += " AND version = ?"
            params.append(version)
        if as_of is not None:
            sql += " AND timestamp <= ?"
            params.append(as_of.isoformat())
        sql += " ORDER BY timestamp"
        return self._query(sql, params)

    def cross_section(
        self, feature: str, as_of: date | datetime, version: int | None = None
    ) -> list[dict]:
        """Latest value per symbol for a feature, as of a date. For factor sorts."""
        sql = """
            SELECT symbol, feature, version, timestamp, value FROM (
                SELECT *, ROW_NUMBER() OVER (
                    PARTITION BY symbol ORDER BY timestamp DESC
                ) AS rn
                FROM feature_values
                WHERE feature = ? AND timestamp <= ?
        """
        params: list = [feature, as_of.isoformat()]
        if version is not None:
            sql += " AND version = ?"
            params.append(version)
        sql += ") WHERE rn = 1 ORDER BY symbol"
        return self._query(sql, params)

    def _query(self, sql: str, params: list) -> list[dict]:
        with self._conn() as conn:
            res = conn.execute(sql, params)
            cols = [d[0] for d in res.description]
            return [dict(zip(cols, row, strict=False)) for row in res.fetchall()]

"""QualityEngine — validates DuckDB-backed datasets across 6 quality dimensions.

Dimensions and default weights (penalty budget = 100):
  missing values     30 pts
  duplicates         20 pts
  timestamp gaps     20 pts
  outliers           10 pts
  schema drift       10 pts
  feed delay         10 pts
"""

from __future__ import annotations

import math
import statistics
from datetime import datetime, timedelta, timezone

import duckdb

from aurelius.catalog.models import DatasetRecord, QualityReport
from aurelius.catalog.store import CatalogStore
from aurelius.core.logging import get_logger

logger = get_logger(__name__)

_W_MISSING = 30.0
_W_DUPE = 20.0
_W_GAPS = 20.0
_W_OUTLIER = 10.0
_W_DRIFT = 10.0
_W_DELAY = 10.0


class QualityEngine:
    """Runs all quality checks against a DuckDB table and saves the report."""

    def __init__(self, catalog: CatalogStore) -> None:
        self._catalog = catalog

    def run(
        self,
        dataset: DatasetRecord,
        db_path: str,
        table: str,
        *,
        date_col: str = "timestamp",
        symbol_col: str | None = "symbol",
        value_cols: list[str] | None = None,
        freshness_days: int = 1,
    ) -> QualityReport:
        """Run all checks, persist report, update dataset quality score."""
        details: dict = {}
        try:
            conn = duckdb.connect(db_path, read_only=True)
            try:
                cols = value_cols or self._numeric_cols(conn, table, exclude={date_col, symbol_col or ""})
                missing_pct = self._check_missing(conn, table, cols, details)
                dupe_count = self._check_duplicates(conn, table, date_col, symbol_col, details)
                gap_count = self._check_gaps(conn, table, date_col, details)
                outlier_count = self._check_outliers(conn, table, cols, details)
                schema_drift = self._check_schema_drift(conn, table, dataset, details)
                feed_delayed = self._check_freshness(conn, table, date_col, freshness_days, details)
            finally:
                conn.close()
        except Exception as exc:
            logger.warning("quality_check_failed", dataset_id=dataset.id, error=str(exc))
            details["error"] = str(exc)
            report = QualityReport(dataset_id=dataset.id, overall_score=0.0, passed=False, details=details)
            self._catalog.save_quality_report(report)
            return report

        score = _score(missing_pct, dupe_count, gap_count, outlier_count, schema_drift, feed_delayed)
        report = QualityReport(
            dataset_id=dataset.id,
            missing_pct=missing_pct,
            duplicate_count=dupe_count,
            timestamp_gaps=gap_count,
            outlier_count=outlier_count,
            schema_drift=schema_drift,
            feed_delayed=feed_delayed,
            overall_score=score,
            details=details,
            passed=score >= 70.0,
        )
        self._catalog.save_quality_report(report)
        logger.info("quality_checked", dataset_id=dataset.id, score=score, passed=report.passed)
        return report

    # ── Individual checks ──────────────────────────────────────────────────────

    @staticmethod
    def _numeric_cols(conn: duckdb.DuckDBPyConnection, table: str, exclude: set[str]) -> list[str]:
        try:
            info = conn.execute(f"PRAGMA table_info('{table}')").fetchall()
            return [c[1] for c in info if c[1] not in exclude and any(
                t in c[2].upper() for t in ("INT", "FLOAT", "DOUBLE", "DECIMAL", "REAL", "NUMERIC")
            )]
        except Exception:
            return []

    @staticmethod
    def _check_missing(
        conn: duckdb.DuckDBPyConnection, table: str, cols: list[str], details: dict
    ) -> float:
        if not cols:
            return 0.0
        pcts = []
        for col in cols:
            try:
                row = conn.execute(
                    f"SELECT COUNT(*) FILTER (WHERE {col} IS NULL)::FLOAT / NULLIF(COUNT(*), 0) FROM {table}"
                ).fetchone()
                pct = float(row[0] or 0.0) * 100
                pcts.append(pct)
                if pct > 0:
                    details[f"missing_{col}_pct"] = round(pct, 2)
            except Exception:
                continue
        return round(statistics.mean(pcts), 2) if pcts else 0.0

    @staticmethod
    def _check_duplicates(
        conn: duckdb.DuckDBPyConnection,
        table: str,
        date_col: str,
        symbol_col: str | None,
        details: dict,
    ) -> int:
        group = f"{symbol_col}, {date_col}" if symbol_col else date_col
        try:
            row = conn.execute(
                f"""
                SELECT COALESCE(SUM(cnt - 1), 0)
                FROM (SELECT COUNT(*) AS cnt FROM {table} GROUP BY {group}) t
                WHERE cnt > 1
                """
            ).fetchone()
            count = int(row[0] or 0)
            if count:
                details["duplicate_count"] = count
            return count
        except Exception:
            return 0

    @staticmethod
    def _check_gaps(
        conn: duckdb.DuckDBPyConnection, table: str, date_col: str, details: dict
    ) -> int:
        try:
            row = conn.execute(
                f"""
                SELECT COUNT(*) FROM (
                    SELECT {date_col},
                           LAG({date_col}) OVER (ORDER BY {date_col}) AS prev
                    FROM (SELECT DISTINCT CAST({date_col} AS DATE) AS {date_col} FROM {table}) t
                ) t2
                WHERE {date_col} - prev > INTERVAL '4 days'
                """
            ).fetchone()
            count = int(row[0] or 0)
            if count:
                details["timestamp_gaps"] = count
            return count
        except Exception:
            return 0

    @staticmethod
    def _check_outliers(
        conn: duckdb.DuckDBPyConnection, table: str, cols: list[str], details: dict
    ) -> int:
        total = 0
        for col in cols[:3]:  # ponytail: cap at 3 cols; add config param if more needed
            try:
                row = conn.execute(
                    f"""
                    SELECT COUNT(*) FROM (
                        SELECT {col},
                               AVG({col}) OVER () AS mu,
                               STDDEV({col}) OVER () AS sigma
                        FROM {table} WHERE {col} IS NOT NULL
                    ) t
                    WHERE sigma > 0 AND ABS({col} - mu) / sigma > 5
                    """
                ).fetchone()
                count = int(row[0] or 0)
                if count:
                    details[f"outliers_{col}"] = count
                total += count
            except Exception:
                continue
        return total

    @staticmethod
    def _check_schema_drift(
        conn: duckdb.DuckDBPyConnection, table: str, dataset: DatasetRecord, details: dict
    ) -> bool:
        if not dataset.schema_def:
            return False
        try:
            current = {c[1] for c in conn.execute(f"PRAGMA table_info('{table}')").fetchall()}
            missing = set(dataset.schema_def.keys()) - current
            if missing:
                details["schema_drift_missing_cols"] = sorted(missing)
                return True
            return False
        except Exception:
            return False

    @staticmethod
    def _check_freshness(
        conn: duckdb.DuckDBPyConnection,
        table: str,
        date_col: str,
        freshness_days: int,
        details: dict,
    ) -> bool:
        try:
            row = conn.execute(f"SELECT MAX(CAST({date_col} AS DATE)) FROM {table}").fetchone()
            if not row or row[0] is None:
                details["feed_status"] = "no_data"
                return True
            latest = datetime.fromisoformat(str(row[0]))
            threshold = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=freshness_days)
            delayed = latest < threshold
            if delayed:
                details["feed_last_date"] = str(row[0])
                details["freshness_threshold_days"] = freshness_days
            return delayed
        except Exception:
            return False


def _score(
    missing_pct: float,
    dupe_count: int,
    gap_count: int,
    outlier_count: int,
    schema_drift: bool,
    feed_delayed: bool,
) -> float:
    penalty = 0.0
    penalty += min(_W_MISSING, missing_pct * 0.3)
    penalty += min(_W_DUPE, math.log1p(dupe_count) * 2)
    penalty += min(_W_GAPS, gap_count * 2)
    penalty += min(_W_OUTLIER, math.log1p(outlier_count))
    if schema_drift:
        penalty += _W_DRIFT
    if feed_delayed:
        penalty += _W_DELAY
    return max(0.0, round(100.0 - penalty, 1))

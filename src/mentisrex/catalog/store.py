"""CatalogStore — DuckDB persistence layer for the Data Intelligence Platform.

Follows the same connection pattern as market_data/storage/duckdb_store.py:
in-memory mode reuses a single persistent connection; file mode opens/closes per call.
"""

from __future__ import annotations

import json
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import duckdb

def _parse_dt(v: object) -> datetime:
    """DuckDB TIMESTAMPTZ returns datetime objects; strings come from tests/manual inserts."""
    if isinstance(v, datetime):
        return v
    return datetime.fromisoformat(str(v))


from mentisrex.catalog.models import (
    DatasetRecord,
    DataVersion,
    GovernanceRecord,
    LineageEdge,
    QualityReport,
)
from mentisrex.core.logging import get_logger

logger = get_logger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS datasets (
    id            VARCHAR PRIMARY KEY,
    name          VARCHAR NOT NULL,
    source        VARCHAR NOT NULL,
    asset_class   VARCHAR,
    frequency     VARCHAR,
    coverage      JSON,
    schema_def    JSON,
    update_freq   VARCHAR,
    license       VARCHAR,
    quality_score DOUBLE DEFAULT 0.0,
    owner         VARCHAR,
    dependencies  JSON,
    tags          JSON,
    description   TEXT,
    created_at    TIMESTAMPTZ,
    updated_at    TIMESTAMPTZ,
    status        VARCHAR DEFAULT 'active'
);

CREATE TABLE IF NOT EXISTS dataset_versions (
    id            VARCHAR PRIMARY KEY,
    dataset_id    VARCHAR NOT NULL,
    version       VARCHAR NOT NULL,
    snapshot_meta JSON,
    row_hash      VARCHAR,
    created_at    TIMESTAMPTZ,
    created_by    VARCHAR,
    notes         TEXT
);

CREATE TABLE IF NOT EXISTS lineage_edges (
    id          VARCHAR PRIMARY KEY,
    source_id   VARCHAR NOT NULL,
    source_type VARCHAR NOT NULL,
    target_id   VARCHAR NOT NULL,
    target_type VARCHAR NOT NULL,
    rel_type    VARCHAR NOT NULL,
    metadata    JSON,
    created_at  TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS quality_reports (
    id              VARCHAR PRIMARY KEY,
    dataset_id      VARCHAR NOT NULL,
    checked_at      TIMESTAMPTZ,
    missing_pct     DOUBLE,
    duplicate_count INTEGER,
    timestamp_gaps  INTEGER,
    outlier_count   INTEGER,
    schema_drift    BOOLEAN,
    feed_delayed    BOOLEAN,
    overall_score   DOUBLE,
    details         JSON,
    passed          BOOLEAN
);

CREATE TABLE IF NOT EXISTS governance_log (
    id             VARCHAR PRIMARY KEY,
    dataset_id     VARCHAR NOT NULL,
    action         VARCHAR NOT NULL,
    actor          VARCHAR,
    details        JSON,
    retention_days INTEGER,
    logged_at      TIMESTAMPTZ
);
"""

# Built-in datasets: existing DuckDB stores + market data store
_BUILTIN_DATASETS: list[DatasetRecord] = [
    DatasetRecord(
        id="corpus_papers", name="Research Corpus", source="internal",
        asset_class="all", frequency="on-demand",
        description="Academic papers corpus managed by CorpusStore",
        owner="system", tags=["corpus", "literature"],
    ),
    DatasetRecord(
        id="hypothesis_store", name="Hypothesis Store", source="internal",
        asset_class="all", frequency="on-demand",
        description="Generated and ranked trading hypotheses",
        owner="system", tags=["hypothesis"],
    ),
    DatasetRecord(
        id="knowledge_graph", name="Knowledge Graph", source="internal",
        asset_class="all", frequency="on-demand",
        description="Property graph of research entities (papers, hypotheses, experiments, features)",
        owner="system", tags=["knowledge", "graph"],
    ),
    DatasetRecord(
        id="literature_papers", name="Literature Store", source="arxiv/nber/crossref",
        asset_class="all", frequency="daily",
        description="Ingested academic papers from arXiv, NBER, CrossRef",
        owner="system", tags=["literature"],
    ),
    DatasetRecord(
        id="research_experiments", name="Research Experiments", source="internal",
        asset_class="all", frequency="on-demand",
        description="Experiment records, validation reports, and verdicts",
        owner="system", tags=["research", "experiments"],
    ),
    DatasetRecord(
        id="paper_trading_outcomes", name="Paper Trading Outcomes", source="internal",
        asset_class="equity", frequency="daily",
        description="Paper trading journal, orders, and performance records",
        owner="system", tags=["paper-trading"],
    ),
    DatasetRecord(
        id="ohlcv_daily_market", name="OHLCV Daily Market Data", source="yahoo/alpaca",
        asset_class="equity", frequency="daily",
        description="Daily OHLCV bars for equities via Yahoo Finance and Alpaca",
        schema_def={"symbol": "VARCHAR", "timestamp": "TIMESTAMPTZ", "open": "DECIMAL",
                    "high": "DECIMAL", "low": "DECIMAL", "close": "DECIMAL", "volume": "DECIMAL"},
        owner="system", tags=["market-data", "ohlcv", "equity"],
    ),
]


class CatalogStore:
    """DuckDB-backed store for the institutional data catalog."""

    def __init__(self, db_path: str = "./data/catalog.duckdb") -> None:
        self._path = db_path
        self._in_memory = db_path == ":memory:"
        self._persistent_conn: duckdb.DuckDBPyConnection | None = None

        if not self._in_memory:
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        else:
            self._persistent_conn = duckdb.connect(":memory:")

        with self._conn() as conn:
            conn.execute(_SCHEMA)

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

    # ── Datasets ──────────────────────────────────────────────────────────────

    def register(self, record: DatasetRecord) -> DatasetRecord:
        with self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO datasets VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                [
                    record.id, record.name, record.source, record.asset_class,
                    record.frequency, json.dumps(record.coverage), json.dumps(record.schema_def),
                    record.update_freq, record.license, record.quality_score, record.owner,
                    json.dumps(record.dependencies), json.dumps(record.tags),
                    record.description, record.created_at.isoformat(),
                    record.updated_at.isoformat(), record.status,
                ],
            )
        logger.info("dataset_registered", id=record.id, name=record.name)
        return record

    def get(self, dataset_id: str) -> DatasetRecord | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM datasets WHERE id = ?", [dataset_id]).fetchone()
        return self._row_to_dataset(row) if row else None

    def list_datasets(
        self,
        source: str | None = None,
        asset_class: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[DatasetRecord]:
        where, params = [], []
        if source:
            where.append("source = ?")
            params.append(source)
        if asset_class:
            where.append("asset_class = ?")
            params.append(asset_class)
        if status:
            where.append("status = ?")
            params.append(status)
        sql = "SELECT * FROM datasets"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += f" ORDER BY created_at DESC LIMIT {limit}"
        with self._conn() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._row_to_dataset(r) for r in rows]

    def update_quality_score(self, dataset_id: str, score: float) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE datasets SET quality_score=?, updated_at=? WHERE id=?",
                [score, datetime.now(timezone.utc).isoformat(), dataset_id],
            )

    def deprecate(self, dataset_id: str, replaced_by: str | None = None) -> None:
        new_status = "replaced" if replaced_by else "deprecated"
        with self._conn() as conn:
            conn.execute(
                "UPDATE datasets SET status=?, updated_at=? WHERE id=?",
                [new_status, datetime.now(timezone.utc).isoformat(), dataset_id],
            )

    def search(self, q: str, limit: int = 20) -> list[DatasetRecord]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM datasets WHERE name ILIKE ? OR description ILIKE ? OR source ILIKE ? LIMIT ?",
                [f"%{q}%", f"%{q}%", f"%{q}%", limit],
            ).fetchall()
        return [self._row_to_dataset(r) for r in rows]

    # ── Versions ──────────────────────────────────────────────────────────────

    def save_version(self, v: DataVersion) -> DataVersion:
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO dataset_versions VALUES (?,?,?,?,?,?,?,?)",
                [
                    v.id, v.dataset_id, v.version, json.dumps(v.snapshot_meta),
                    v.row_hash, v.created_at.isoformat(), v.created_by, v.notes,
                ],
            )
        logger.info("version_saved", dataset_id=v.dataset_id, version=v.version)
        return v

    def list_versions(self, dataset_id: str) -> list[DataVersion]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM dataset_versions WHERE dataset_id=? ORDER BY created_at DESC",
                [dataset_id],
            ).fetchall()
        return [self._row_to_version(r) for r in rows]

    # ── Lineage ───────────────────────────────────────────────────────────────

    def add_lineage_edge(self, edge: LineageEdge) -> LineageEdge:
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO lineage_edges VALUES (?,?,?,?,?,?,?,?)",
                [
                    edge.id, edge.source_id, edge.source_type,
                    edge.target_id, edge.target_type, edge.rel_type,
                    json.dumps(edge.metadata), edge.created_at.isoformat(),
                ],
            )
        return edge

    def get_lineage(self, node_id: str) -> list[LineageEdge]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM lineage_edges WHERE source_id=? OR target_id=? LIMIT 500",
                [node_id, node_id],
            ).fetchall()
        return [self._row_to_edge(r) for r in rows]

    # ── Quality ───────────────────────────────────────────────────────────────

    def save_quality_report(self, report: QualityReport) -> QualityReport:
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO quality_reports VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                [
                    report.id, report.dataset_id, report.checked_at.isoformat(),
                    report.missing_pct, report.duplicate_count, report.timestamp_gaps,
                    report.outlier_count, report.schema_drift, report.feed_delayed,
                    report.overall_score, json.dumps(report.details), report.passed,
                ],
            )
        self.update_quality_score(report.dataset_id, report.overall_score)
        return report

    def latest_quality_report(self, dataset_id: str) -> QualityReport | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM quality_reports WHERE dataset_id=? ORDER BY checked_at DESC LIMIT 1",
                [dataset_id],
            ).fetchone()
        return self._row_to_quality(row) if row else None

    # ── Governance ────────────────────────────────────────────────────────────

    def log_governance(self, rec: GovernanceRecord) -> GovernanceRecord:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO governance_log VALUES (?,?,?,?,?,?,?)",
                [
                    rec.id, rec.dataset_id, rec.action, rec.actor,
                    json.dumps(rec.details), rec.retention_days, rec.logged_at.isoformat(),
                ],
            )
        return rec

    def governance_history(self, dataset_id: str) -> list[GovernanceRecord]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM governance_log WHERE dataset_id=? ORDER BY logged_at DESC",
                [dataset_id],
            ).fetchall()
        return [self._row_to_governance(r) for r in rows]

    # ── Bootstrap ─────────────────────────────────────────────────────────────

    def bootstrap(self) -> None:
        """Register built-in datasets if not already present."""
        for ds in _BUILTIN_DATASETS:
            if self.get(ds.id) is None:
                self.register(ds)
        logger.info("catalog_bootstrapped", count=len(_BUILTIN_DATASETS))

    # ── Row mappers ───────────────────────────────────────────────────────────

    @staticmethod
    def _row_to_dataset(row: tuple) -> DatasetRecord:
        return DatasetRecord(
            id=row[0], name=row[1], source=row[2], asset_class=row[3],
            frequency=row[4], coverage=json.loads(row[5] or "{}"),
            schema_def=json.loads(row[6] or "{}"), update_freq=row[7],
            license=row[8], quality_score=float(row[9] or 0.0), owner=row[10],
            dependencies=json.loads(row[11] or "[]"), tags=json.loads(row[12] or "[]"),
            description=row[13] or "", created_at=_parse_dt(row[14]),
            updated_at=_parse_dt(row[15]), status=row[16],
        )

    @staticmethod
    def _row_to_version(row: tuple) -> DataVersion:
        return DataVersion(
            id=row[0], dataset_id=row[1], version=row[2],
            snapshot_meta=json.loads(row[3] or "{}"), row_hash=row[4] or "",
            created_at=_parse_dt(row[5]),
            created_by=row[6] or "system", notes=row[7] or "",
        )

    @staticmethod
    def _row_to_edge(row: tuple) -> LineageEdge:
        return LineageEdge(
            id=row[0], source_id=row[1], source_type=row[2],
            target_id=row[3], target_type=row[4], rel_type=row[5],
            metadata=json.loads(row[6] or "{}"),
            created_at=_parse_dt(row[7]),
        )

    @staticmethod
    def _row_to_quality(row: tuple) -> QualityReport:
        return QualityReport(
            id=row[0], dataset_id=row[1],
            checked_at=_parse_dt(row[2]),
            missing_pct=float(row[3] or 0.0),
            duplicate_count=int(row[4] or 0),
            timestamp_gaps=int(row[5] or 0),
            outlier_count=int(row[6] or 0),
            schema_drift=bool(row[7]),
            feed_delayed=bool(row[8]),
            overall_score=float(row[9] or 0.0),
            details=json.loads(row[10] or "{}"),
            passed=bool(row[11]),
        )

    @staticmethod
    def _row_to_governance(row: tuple) -> GovernanceRecord:
        return GovernanceRecord(
            id=row[0], dataset_id=row[1], action=row[2],
            actor=row[3] or "system",
            details=json.loads(row[4] or "{}"),
            retention_days=row[5],
            logged_at=_parse_dt(row[6]),
        )

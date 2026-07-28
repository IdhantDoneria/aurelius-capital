"""DuckDB-backed hypothesis repository with version history."""
from __future__ import annotations

import json
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from pathlib import Path

import duckdb

from aurelius.core.logging import get_logger
from aurelius.hypothesis.models import HypothesisRecord

logger = get_logger(__name__)

_CREATE_HYPOTHESES = """
CREATE TABLE IF NOT EXISTS hypotheses (
    id                      VARCHAR PRIMARY KEY,
    parent_papers           VARCHAR NOT NULL,
    research_category       VARCHAR,
    economic_intuition      VARCHAR,
    testable_statement      VARCHAR NOT NULL,
    expected_behavior       VARCHAR,
    asset_classes           VARCHAR,
    required_datasets       VARCHAR,
    required_features       VARCHAR,
    holding_period          VARCHAR,
    expected_risks          VARCHAR,
    confidence_score        DOUBLE,
    assumptions             VARCHAR,
    dependencies            VARCHAR,
    validation_requirements VARCHAR,
    similar_to              VARCHAR,
    status                  VARCHAR NOT NULL DEFAULT 'Draft',
    version                 INTEGER NOT NULL DEFAULT 1,
    created_at              TIMESTAMPTZ NOT NULL,
    updated_at              TIMESTAMPTZ NOT NULL,
    researcher              VARCHAR NOT NULL,
    generation_method       VARCHAR NOT NULL,
    rejection_reason        VARCHAR
)
"""

_CREATE_VERSIONS = """
CREATE TABLE IF NOT EXISTS hypothesis_versions (
    hypothesis_id   VARCHAR NOT NULL,
    version         INTEGER NOT NULL,
    snapshot        VARCHAR NOT NULL,
    changed_at      TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (hypothesis_id, version)
)
"""


class HypothesisStore:
    def __init__(self, db_path: str = "./data/hypothesis.duckdb") -> None:
        self._path = db_path
        self._in_memory = db_path == ":memory:"
        self._persistent_conn: duckdb.DuckDBPyConnection | None = None
        if not self._in_memory:
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        else:
            self._persistent_conn = duckdb.connect(":memory:")
        with self._conn() as conn:
            conn.execute(_CREATE_HYPOTHESES)
            conn.execute(_CREATE_VERSIONS)

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

    def insert(self, h: HypothesisRecord) -> bool:
        """Insert new hypothesis. Returns True if inserted, False if ID already exists."""
        with self._conn() as conn:
            existing = conn.execute(
                "SELECT 1 FROM hypotheses WHERE id=?", [h.id]
            ).fetchone()
            if existing:
                return False
            conn.execute(
                "INSERT INTO hypotheses VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                self._to_row(h),
            )
            self._save_version(conn, h)
            return True

    def update(self, h: HypothesisRecord) -> None:
        """Update hypothesis, increment version, save version snapshot."""
        with self._conn() as conn:
            current = conn.execute(
                "SELECT version FROM hypotheses WHERE id=?", [h.id]
            ).fetchone()
            if current is None:
                raise KeyError(f"Hypothesis {h.id} not found")
            h.version = current[0] + 1
            h.updated_at = datetime.now(UTC)
            conn.execute(
                """UPDATE hypotheses SET
                    parent_papers=?, research_category=?, economic_intuition=?,
                    testable_statement=?, expected_behavior=?, asset_classes=?,
                    required_datasets=?, required_features=?, holding_period=?,
                    expected_risks=?, confidence_score=?, assumptions=?,
                    dependencies=?, validation_requirements=?, similar_to=?,
                    status=?, version=?, updated_at=?, researcher=?,
                    generation_method=?, rejection_reason=?
                WHERE id=?""",
                [
                    json.dumps(h.parent_papers), h.research_category,
                    h.economic_intuition, h.testable_statement, h.expected_behavior,
                    json.dumps(h.asset_classes), json.dumps(h.required_datasets),
                    json.dumps(h.required_features), h.holding_period,
                    json.dumps(h.expected_risks), h.confidence_score,
                    json.dumps(h.assumptions), json.dumps(h.dependencies),
                    json.dumps(h.validation_requirements), json.dumps(h.similar_to),
                    h.status, h.version, h.updated_at, h.researcher,
                    h.generation_method, h.rejection_reason,
                    h.id,
                ],
            )
            self._save_version(conn, h)

    def get(self, hypothesis_id: str) -> HypothesisRecord | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM hypotheses WHERE id=?", [hypothesis_id]
            ).fetchone()
            return self._row_to_record(row) if row else None

    def search(
        self,
        query: str | None = None,
        category: str | None = None,
        status: str | None = None,
        asset_class: str | None = None,
        paper_id: str | None = None,
        method: str | None = None,
        since: date | None = None,
        limit: int = 50,
    ) -> list[HypothesisRecord]:
        clauses: list[str] = []
        params: list = []

        if query:
            clauses.append(
                "(testable_statement ILIKE ? OR economic_intuition ILIKE ?)"
            )
            params += [f"%{query}%", f"%{query}%"]
        if category:
            clauses.append("research_category = ?")
            params.append(category)
        if status:
            clauses.append("status = ?")
            params.append(status)
        if asset_class:
            clauses.append("asset_classes ILIKE ?")
            params.append(f"%{asset_class}%")
        if paper_id:
            clauses.append("parent_papers ILIKE ?")
            params.append(f"%{paper_id}%")
        if method:
            clauses.append("generation_method = ?")
            params.append(method)
        if since:
            clauses.append("created_at >= ?")
            params.append(since)

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"SELECT * FROM hypotheses {where} ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        with self._conn() as conn:
            rows = conn.execute(sql, params).fetchall()
            return [self._row_to_record(r) for r in rows]

    def get_by_paper(self, paper_id: str) -> list[HypothesisRecord]:
        return self.search(paper_id=paper_id, limit=200)

    def get_versions(self, hypothesis_id: str) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT version, snapshot, changed_at FROM hypothesis_versions "
                "WHERE hypothesis_id=? ORDER BY version",
                [hypothesis_id],
            ).fetchall()
            return [
                {"version": r[0], "snapshot": json.loads(r[1]), "changed_at": str(r[2])}
                for r in rows
            ]

    def all_statements(self) -> list[tuple[str, str]]:
        """Return (id, testable_statement) for all non-rejected hypotheses."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, testable_statement FROM hypotheses WHERE status != 'Rejected'"
            ).fetchall()
            return [(r[0], r[1]) for r in rows]

    def stats(self) -> dict:
        with self._conn() as conn:
            total = conn.execute("SELECT COUNT(*) FROM hypotheses").fetchone()[0]
            by_status = conn.execute(
                "SELECT status, COUNT(*) FROM hypotheses GROUP BY status ORDER BY status"
            ).fetchall()
            by_category = conn.execute(
                "SELECT research_category, COUNT(*) FROM hypotheses "
                "WHERE status != 'Rejected' GROUP BY research_category ORDER BY research_category"
            ).fetchall()
            by_method = conn.execute(
                "SELECT generation_method, COUNT(*) FROM hypotheses GROUP BY generation_method"
            ).fetchall()
            return {
                "total": total,
                "by_status": {r[0]: r[1] for r in by_status},
                "by_category": {r[0] or "unknown": r[1] for r in by_category},
                "by_method": {r[0]: r[1] for r in by_method},
            }

    # ── helpers ───────────────────────────────────────────────────────────────

    def _save_version(self, conn: duckdb.DuckDBPyConnection, h: HypothesisRecord) -> None:
        snapshot = json.dumps({
            "id": h.id, "testable_statement": h.testable_statement,
            "economic_intuition": h.economic_intuition, "status": h.status,
            "version": h.version, "researcher": h.researcher,
        })
        conn.execute(
            "INSERT OR REPLACE INTO hypothesis_versions VALUES (?,?,?,?)",
            [h.id, h.version, snapshot, datetime.now(UTC)],
        )

    def _to_row(self, h: HypothesisRecord) -> list:
        return [
            h.id, json.dumps(h.parent_papers), h.research_category,
            h.economic_intuition, h.testable_statement, h.expected_behavior,
            json.dumps(h.asset_classes), json.dumps(h.required_datasets),
            json.dumps(h.required_features), h.holding_period,
            json.dumps(h.expected_risks), h.confidence_score,
            json.dumps(h.assumptions), json.dumps(h.dependencies),
            json.dumps(h.validation_requirements), json.dumps(h.similar_to),
            h.status, h.version, h.created_at, h.updated_at,
            h.researcher, h.generation_method, h.rejection_reason,
        ]

    def _row_to_record(self, row: tuple) -> HypothesisRecord:
        (
            id_, parent_papers_j, research_category, economic_intuition,
            testable_statement, expected_behavior, asset_classes_j,
            required_datasets_j, required_features_j, holding_period,
            expected_risks_j, confidence_score, assumptions_j, dependencies_j,
            validation_requirements_j, similar_to_j, status, version,
            created_at, updated_at, researcher, generation_method, rejection_reason,
        ) = row

        def _ts(v) -> datetime:
            return v if isinstance(v, datetime) else datetime.fromisoformat(str(v))

        return HypothesisRecord(
            id=id_,
            parent_papers=json.loads(parent_papers_j or "[]"),
            research_category=research_category or "",
            economic_intuition=economic_intuition or "",
            testable_statement=testable_statement,
            expected_behavior=expected_behavior or "",
            asset_classes=json.loads(asset_classes_j or "[]"),
            required_datasets=json.loads(required_datasets_j or "[]"),
            required_features=json.loads(required_features_j or "[]"),
            holding_period=holding_period or "",
            expected_risks=json.loads(expected_risks_j or "[]"),
            confidence_score=float(confidence_score or 0.0),
            assumptions=json.loads(assumptions_j or "[]"),
            dependencies=json.loads(dependencies_j or "[]"),
            validation_requirements=json.loads(validation_requirements_j or "[]"),
            similar_to=json.loads(similar_to_j or "[]"),
            status=status,
            version=int(version),
            created_at=_ts(created_at),
            updated_at=_ts(updated_at),
            researcher=researcher,
            generation_method=generation_method,
            rejection_reason=rejection_reason or "",
        )

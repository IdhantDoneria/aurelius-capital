"""Research database: hypotheses, experiments, results, rejected ideas.

DuckDB-backed (same pattern as the feature store). The institutional memory that
makes research fast: every experiment and its verdict is recorded, so a rejected
idea is queryable and never silently rerun. Trial counts feed the data-mining
correction.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import duckdb

from aurelius.core.logging import get_logger
from aurelius.research.models import ExperimentRecord, Hypothesis, Verdict

logger = get_logger(__name__)

_CREATE_HYPOTHESES = """
CREATE TABLE IF NOT EXISTS hypotheses (
    id          VARCHAR     PRIMARY KEY,
    statement   VARCHAR     NOT NULL,
    rationale   VARCHAR,
    researcher  VARCHAR     NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL,
    status      VARCHAR     NOT NULL DEFAULT 'open'
)
"""

_CREATE_EXPERIMENTS = """
CREATE TABLE IF NOT EXISTS experiments (
    id               VARCHAR     PRIMARY KEY,
    hypothesis_id    VARCHAR     NOT NULL,
    researcher       VARCHAR     NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL,
    dataset_version  VARCHAR     NOT NULL,
    strategy_name    VARCHAR     NOT NULL,
    strategy_version INTEGER     NOT NULL,
    features_used    VARCHAR,
    params           VARCHAR,
    verdict          VARCHAR     NOT NULL,
    reasons          VARCHAR,
    is_sharpe        DOUBLE,
    oos_sharpe       DOUBLE,
    oos_return       DOUBLE,
    oos_max_drawdown DOUBLE,
    oos_trades       INTEGER,
    n_trials         INTEGER,
    adjusted_pvalue  DOUBLE,
    config_snapshot  VARCHAR
)
"""


class ResearchStore:
    def __init__(self, db_path: str = "./data/research.duckdb") -> None:
        self._path = db_path
        self._in_memory = db_path == ":memory:"
        self._persistent_conn: duckdb.DuckDBPyConnection | None = None
        if not self._in_memory:
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        else:
            self._persistent_conn = duckdb.connect(":memory:")
        with self._conn() as conn:
            conn.execute(_CREATE_HYPOTHESES)
            conn.execute(_CREATE_EXPERIMENTS)

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

    # ── hypotheses ──

    def record_hypothesis(self, statement: str, rationale: str, researcher: str) -> Hypothesis:
        h = Hypothesis(
            id=str(uuid.uuid4()),
            statement=statement,
            rationale=rationale,
            researcher=researcher,
            created_at=datetime.now(UTC),
        )
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO hypotheses VALUES (?,?,?,?,?,?)",
                [h.id, h.statement, h.rationale, h.researcher, h.created_at, h.status],
            )
        return h

    def set_hypothesis_status(self, hypothesis_id: str, status: str) -> None:
        with self._conn() as conn:
            conn.execute("UPDATE hypotheses SET status = ? WHERE id = ?", [status, hypothesis_id])

    # ── experiments ──

    def trial_count(self, hypothesis_id: str) -> int:
        """Number of experiments already run against this hypothesis."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM experiments WHERE hypothesis_id = ?", [hypothesis_id]
            ).fetchone()
        return int(row[0]) if row else 0

    def find_duplicate(
        self,
        dataset_version: str,
        strategy_name: str,
        strategy_version: int,
        params: dict,
        config_snapshot: dict | None = None,
    ) -> str | None:
        """Return an existing experiment id for the same run identity, else None.

        Reproducibility + velocity: don't rerun an identical experiment.
        """
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, params, config_snapshot FROM experiments WHERE dataset_version = ? "
                "AND strategy_name = ? AND strategy_version = ?",
                [dataset_version, strategy_name, strategy_version],
            ).fetchall()
        target_params = json.dumps(params, sort_keys=True, default=str)
        target_config = json.dumps(config_snapshot or {}, sort_keys=True, default=str)
        for exp_id, stored_params, stored_config in rows:
            if stored_params == target_params and (stored_config or "{}") == target_config:
                return exp_id
        return None

    def record_experiment(self, rec: ExperimentRecord) -> None:
        r = rec.report
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO experiments VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [
                    rec.id,
                    rec.hypothesis_id,
                    rec.researcher,
                    rec.created_at,
                    rec.dataset_version,
                    rec.strategy_name,
                    rec.strategy_version,
                    ",".join(rec.features_used),
                    json.dumps(rec.params, sort_keys=True, default=str),
                    r.verdict.value,
                    " | ".join(r.reasons),
                    r.is_sharpe,
                    r.oos_sharpe,
                    r.oos_return,
                    r.oos_max_drawdown,
                    r.oos_trades,
                    r.n_trials,
                    r.adjusted_pvalue,
                    json.dumps(rec.config_snapshot, sort_keys=True, default=str),
                ],
            )
        logger.info(
            "experiment_recorded",
            id=rec.id,
            verdict=r.verdict.value,
            oos_sharpe=round(r.oos_sharpe, 3),
        )

    def experiments_for(self, hypothesis_id: str) -> list[dict]:
        return self._query(
            "SELECT * FROM experiments WHERE hypothesis_id = ? ORDER BY created_at",
            [hypothesis_id],
        )

    def rejected_ideas(self) -> list[dict]:
        """Every rejected experiment. The graveyard that prevents repeat mistakes."""
        return self._query(
            "SELECT hypothesis_id, strategy_name, params, reasons, oos_sharpe "
            "FROM experiments WHERE verdict = ? ORDER BY created_at",
            [Verdict.REJECT.value],
        )

    def _query(self, sql: str, params: list) -> list[dict]:
        with self._conn() as conn:
            res = conn.execute(sql, params)
            cols = [d[0] for d in res.description]
            return [dict(zip(cols, row, strict=False)) for row in res.fetchall()]

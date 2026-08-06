"""DuckDB-backed experiment registry storage (AIDP Phase 7).

Six tables (data/research_registry.duckdb). The `experiments` row holds metadata +
lineage + run identity; the satellite tables hold the variable-length parts
(versions, parameters, features, metrics, artifacts). Native DuckDB, no ML
tracking framework.

Additive columns beyond the spec's list — `fingerprint`, `parameter_hash`,
`duplicate_of`, `error` — are the run-identity/failure fields the registry needs;
they don't alter any Phase 1-6 schema.
"""

from __future__ import annotations

import json
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import duckdb

from aurelius.research.experiment_registry.lineage import VERSION_FIELDS
from aurelius.research.experiment_registry.models import Experiment

_CREATE = """
CREATE TABLE IF NOT EXISTS experiments (
    experiment_id    VARCHAR PRIMARY KEY,
    name             VARCHAR,
    description      VARCHAR,
    status           VARCHAR,
    created_at       TIMESTAMP,
    started_at       TIMESTAMP,
    finished_at      TIMESTAMP,
    duration_seconds DOUBLE,
    git_commit       VARCHAR,
    git_branch       VARCHAR,
    python_version   VARCHAR,
    platform         VARCHAR,
    hostname         VARCHAR,
    "user"           VARCHAR,
    random_seed      BIGINT,
    notes            VARCHAR,
    fingerprint      VARCHAR,
    parameter_hash   VARCHAR,
    duplicate_of     VARCHAR,
    error            VARCHAR
);
CREATE TABLE IF NOT EXISTS dataset_versions (
    experiment_id            VARCHAR,
    prices_version           BIGINT,
    fundamentals_version     BIGINT,
    insiders_version         BIGINT,
    universe_version         BIGINT,
    securitymaster_version   BIGINT,
    feature_registry_version VARCHAR,
    research_matrix_version  VARCHAR
);
CREATE TABLE IF NOT EXISTS parameter_sets (
    experiment_id  VARCHAR,
    parameter_name VARCHAR,
    parameter_value VARCHAR          -- json-encoded, so any type round-trips
);
CREATE TABLE IF NOT EXISTS feature_sets (
    experiment_id VARCHAR,
    feature_name  VARCHAR
);
CREATE TABLE IF NOT EXISTS performance_metrics (
    experiment_id VARCHAR,
    metric_name   VARCHAR,
    metric_value  DOUBLE
);
CREATE TABLE IF NOT EXISTS artifacts (
    experiment_id     VARCHAR,
    artifact_type     VARCHAR,
    artifact_location VARCHAR,
    artifact_hash     VARCHAR
);
CREATE INDEX IF NOT EXISTS ix_exp_fp ON experiments(fingerprint);
CREATE INDEX IF NOT EXISTS ix_exp_created ON experiments(created_at);
"""

_EXP_COLS = ("experiment_id", "name", "description", "status", "created_at", "started_at",
             "finished_at", "duration_seconds", "git_commit", "git_branch", "python_version",
             "platform", "hostname", "user", "random_seed", "notes", "fingerprint",
             "parameter_hash", "duplicate_of", "error")
# `user` is a DuckDB reserved word → quote it in SQL
_EXP_SQL = ", ".join(f'"{c}"' if c == "user" else c for c in _EXP_COLS)


class RegistryStore:
    def __init__(self, db_path: str = "./data/research_registry.duckdb") -> None:
        self._path = db_path
        self._in_memory = db_path == ":memory:"
        self._persistent_conn: duckdb.DuckDBPyConnection | None = None
        if not self._in_memory:
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        else:
            self._persistent_conn = duckdb.connect(":memory:")
        with self._conn() as conn:
            conn.execute(_CREATE)

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

    # ── writes ────────────────────────────────────────────────────────────────

    def insert(self, exp: Experiment) -> None:
        vals = [self._exp_val(exp, c) for c in _EXP_COLS]
        with self._conn() as conn:
            conn.execute(
                f"INSERT OR REPLACE INTO experiments ({_EXP_SQL}) VALUES ({', '.join('?' * len(_EXP_COLS))})",
                vals,
            )
            conn.execute("DELETE FROM dataset_versions WHERE experiment_id = ?", [exp.experiment_id])
            conn.execute(
                f"INSERT INTO dataset_versions (experiment_id, {', '.join(VERSION_FIELDS)}) "
                f"VALUES (?, {', '.join('?' * len(VERSION_FIELDS))})",
                [exp.experiment_id, *(exp.dataset_versions.get(f) for f in VERSION_FIELDS)],
            )
            conn.execute("DELETE FROM parameter_sets WHERE experiment_id = ?", [exp.experiment_id])
            for k, v in exp.parameters.items():
                conn.execute("INSERT INTO parameter_sets VALUES (?, ?, ?)",
                             [exp.experiment_id, k, json.dumps(v)])
            conn.execute("DELETE FROM feature_sets WHERE experiment_id = ?", [exp.experiment_id])
            for f in exp.features:
                conn.execute("INSERT INTO feature_sets VALUES (?, ?)", [exp.experiment_id, f])
            self._write_metrics(conn, exp.experiment_id, exp.metrics)
            self._write_artifacts(conn, exp.experiment_id, exp.artifacts)

    @staticmethod
    def _exp_val(exp: Experiment, col: str):
        return getattr(exp, "user" if col == "user" else col)

    def update_run(self, exp: Experiment) -> None:
        """Persist status transition + metrics + artifacts on finish/fail."""
        with self._conn() as conn:
            conn.execute(
                "UPDATE experiments SET status=?, finished_at=?, duration_seconds=?, "
                "error=?, notes=? WHERE experiment_id=?",
                [exp.status, exp.finished_at, exp.duration_seconds, exp.error,
                 exp.notes, exp.experiment_id],
            )
            self._write_metrics(conn, exp.experiment_id, exp.metrics)
            self._write_artifacts(conn, exp.experiment_id, exp.artifacts)

    @staticmethod
    def _write_metrics(conn, exp_id: str, metrics: dict) -> None:
        conn.execute("DELETE FROM performance_metrics WHERE experiment_id = ?", [exp_id])
        for name, val in (metrics or {}).items():
            conn.execute("INSERT INTO performance_metrics VALUES (?, ?, ?)", [exp_id, name, float(val)])

    @staticmethod
    def _write_artifacts(conn, exp_id: str, artifacts: list[dict]) -> None:
        conn.execute("DELETE FROM artifacts WHERE experiment_id = ?", [exp_id])
        for a in artifacts or []:
            conn.execute("INSERT INTO artifacts VALUES (?, ?, ?, ?)",
                         [exp_id, a.get("artifact_type"), a.get("artifact_location"), a.get("artifact_hash")])

    # ── reads ─────────────────────────────────────────────────────────────────

    def get(self, experiment_id: str) -> Experiment | None:
        with self._conn() as conn:
            row = conn.execute(
                f"SELECT {_EXP_SQL} FROM experiments WHERE experiment_id = ?", [experiment_id],
            ).fetchone()
            if row is None:
                return None
            dv = conn.execute(
                f"SELECT {', '.join(VERSION_FIELDS)} FROM dataset_versions WHERE experiment_id = ?",
                [experiment_id],
            ).fetchone()
            params = conn.execute(
                "SELECT parameter_name, parameter_value FROM parameter_sets WHERE experiment_id = ?",
                [experiment_id]).fetchall()
            feats = conn.execute(
                "SELECT feature_name FROM feature_sets WHERE experiment_id = ?", [experiment_id]).fetchall()
            metrics = conn.execute(
                "SELECT metric_name, metric_value FROM performance_metrics WHERE experiment_id = ?",
                [experiment_id]).fetchall()
            arts = conn.execute(
                "SELECT artifact_type, artifact_location, artifact_hash FROM artifacts WHERE experiment_id = ?",
                [experiment_id]).fetchall()
        exp = Experiment(**dict(zip(_EXP_COLS[:-4], row[:-4], strict=True)),
                         fingerprint=row[16], parameter_hash=row[17],
                         duplicate_of=row[18], error=row[19])
        exp.dataset_versions = dict(zip(VERSION_FIELDS, dv, strict=True)) if dv else {}
        exp.parameters = {k: json.loads(v) for k, v in params}
        exp.features = [f[0] for f in feats]
        exp.metrics = {k: v for k, v in metrics}
        exp.artifacts = [{"artifact_type": t, "artifact_location": loc, "artifact_hash": h}
                         for t, loc, h in arts]
        return exp

    def latest(self) -> Experiment | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT experiment_id FROM experiments ORDER BY created_at DESC, experiment_id DESC LIMIT 1"
            ).fetchone()
        return self.get(row[0]) if row else None

    def find_by_fingerprint(self, fingerprint: str) -> str | None:
        """Oldest non-duplicate experiment with this fingerprint (the canonical original)."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT experiment_id FROM experiments WHERE fingerprint = ? AND duplicate_of IS NULL "
                "ORDER BY created_at ASC, experiment_id ASC LIMIT 1", [fingerprint],
            ).fetchone()
        return row[0] if row else None

    def search(self, *, name: str | None = None, status: str | None = None,
               git_commit: str | None = None, fingerprint: str | None = None,
               limit: int = 100) -> list[Experiment]:
        clauses, params = [], []
        for col, val in (("name", name), ("status", status),
                         ("git_commit", git_commit), ("fingerprint", fingerprint)):
            if val is not None:
                clauses.append(f"{col} = ?")
                params.append(val)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._conn() as conn:
            ids = conn.execute(
                f"SELECT experiment_id FROM experiments {where} "
                f"ORDER BY created_at DESC, experiment_id DESC LIMIT ?", [*params, limit],
            ).fetchall()
        return [self.get(i[0]) for i in ids]

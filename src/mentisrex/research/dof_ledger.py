"""Research degrees-of-freedom ledger (M33, §XIII).

The data-snooping hole: `ResearchStore.trial_count` counts experiments *per
hypothesis id*. A researcher who tests one mechanism (e.g. "momentum works")
across 50 separate hypothesis ids sees `prior_trials≈0` on each, so the
deflated-Sharpe / Bonferroni haircut under-corrects and false positives leak
through.

This ledger counts effective degrees of freedom per **research family** — the
shared economic question / mechanism — across every hypothesis, variant,
dataset, period, and parameter set actually tried. Identical trials (same
fingerprint) are deduplicated so honest re-runs don't inflate the count.
`effective_trials(family)` is the number that should feed `n_trials`.

Self-contained DuckDB store, same pattern as the other research stores.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import duckdb

_CREATE = """
CREATE TABLE IF NOT EXISTS research_trials (
    trial_id       VARCHAR PRIMARY KEY,
    family         VARCHAR NOT NULL,
    hypothesis_id  VARCHAR,
    variant        VARCHAR,
    dataset_id     VARCHAR,
    period         VARCHAR,
    param_hash     VARCHAR,
    selection_note VARCHAR,
    fingerprint    VARCHAR NOT NULL,
    created_at     TIMESTAMP NOT NULL
);
"""


def _param_hash(params: dict | None) -> str:
    blob = json.dumps(params or {}, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha1(blob.encode()).hexdigest()[:16]


def _fingerprint(family, hypothesis_id, variant, dataset_id, period, param_hash) -> str:
    canon = "|".join(
        str(x) for x in (family, hypothesis_id, variant, dataset_id, period, param_hash)
    )
    return hashlib.sha1(canon.encode()).hexdigest()


@dataclass(frozen=True)
class Trial:
    family: str
    hypothesis_id: str | None = None
    variant: str | None = None
    dataset_id: str | None = None
    period: str | None = None
    params: dict = field(default_factory=dict)
    selection_note: str | None = None


class DoFLedger:
    def __init__(self, db_path: str = "./data/dof_ledger.duckdb") -> None:
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

    def record(self, trial: Trial) -> bool:
        """Record one trial. Returns True if newly counted, False if it duplicates
        an existing (fingerprint-identical) trial."""
        ph = _param_hash(trial.params)
        fp = _fingerprint(
            trial.family, trial.hypothesis_id, trial.variant, trial.dataset_id, trial.period, ph
        )
        with self._conn() as conn:
            exists = conn.execute(
                "SELECT 1 FROM research_trials WHERE fingerprint = ? LIMIT 1", [fp]
            ).fetchone()
            if exists:
                return False
            conn.execute(
                "INSERT INTO research_trials VALUES (?,?,?,?,?,?,?,?,?,?)",
                [
                    str(uuid.uuid4()),
                    trial.family,
                    trial.hypothesis_id,
                    trial.variant,
                    trial.dataset_id,
                    trial.period,
                    ph,
                    trial.selection_note,
                    fp,
                    datetime.now(UTC),
                ],
            )
        return True

    def effective_trials(self, family: str) -> int:
        """Distinct trials tried within a family — the value to feed `n_trials`."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT COUNT(DISTINCT fingerprint) FROM research_trials WHERE family = ?",
                [family],
            ).fetchone()
        return int(row[0]) if row else 0

    def breakdown(self, family: str) -> dict:
        """The §XIII search-axis counts: distinct hypotheses, variants, datasets,
        periods, parameter sets, and total trials for a family."""
        with self._conn() as conn:
            row = conn.execute(
                """SELECT COUNT(DISTINCT hypothesis_id), COUNT(DISTINCT variant),
                          COUNT(DISTINCT dataset_id), COUNT(DISTINCT period),
                          COUNT(DISTINCT param_hash), COUNT(DISTINCT fingerprint)
                   FROM research_trials WHERE family = ?""",
                [family],
            ).fetchone()
        keys = ("hypotheses", "variants", "datasets", "periods", "parameter_sets", "trials")
        return (
            dict(zip(keys, (int(x) for x in row), strict=True)) if row else dict.fromkeys(keys, 0)
        )

    def families(self) -> list[str]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT DISTINCT family FROM research_trials ORDER BY family"
            ).fetchall()
        return [r[0] for r in rows]

    def n_trials_for(self, family: str, grid_size: int = 1) -> int:
        """DoF-aware `n_trials` for DSR/Bonferroni: family history + this run's grid.
        Mirrors the runner's `prior_trials + grid_size`, but family-scoped so
        cross-hypothesis snooping is counted."""
        return self.effective_trials(family) + max(grid_size, 1)

"""Factor campaign runner (M35) — closes the research loop over M31–M34.

For each candidate factor this:
  1. evaluates it multi-date (`evaluate_factor`, M34),
  2. logs the trial to the degrees-of-freedom ledger (`DoFLedger`, M33) so the
     family's `n_trials` reflects the true search,
  3. screens it against the existing factor library for redundancy — by
     long-short *return* correlation (the standard multi-factor test: two factors
     with 0.9-correlated returns are one bet, whatever their formulas),
  4. assigns a status from DoF-corrected significance + redundancy, and persists
     the evaluation immutably.

Status:
  INSIGNIFICANT  |ic_t_stat| below t_min (HAC-robust, M31)
  REDUNDANT      duplicates an existing factor's return stream
  PROMISING      significant and independent

Persistence is a small DuckDB store, same pattern as the other research stores.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import numpy as np

from mentisrex.research.cross_sectional import spearman
from mentisrex.research.dof_ledger import DoFLedger, Trial
from mentisrex.research.factor_research import FactorReport, evaluate_factor

_CREATE = """
CREATE TABLE IF NOT EXISTS factor_evaluations (
    factor_id     VARCHAR PRIMARY KEY,
    name          VARCHAR NOT NULL,
    family        VARCHAR NOT NULL,
    ic_mean       DOUBLE,
    ic_ir         DOUBLE,
    ic_t_stat     DOUBLE,
    ls_sharpe     DOUBLE,
    turnover      DOUBLE,
    status        VARCHAR NOT NULL,
    redundant_with VARCHAR,
    ls_series     VARCHAR,
    fingerprint   VARCHAR NOT NULL,
    created_at    TIMESTAMP NOT NULL
);
"""


def _fingerprint(name: str, family: str, ls_series: list) -> str:
    blob = json.dumps({"n": name, "f": family, "ls": [round(x, 10) for x in ls_series]},
                      sort_keys=True)
    return hashlib.sha1(blob.encode()).hexdigest()


def _series_corr(a: list, b: list) -> float:
    """Spearman correlation of two return series on their overlapping prefix."""
    n = min(len(a), len(b))
    if n < 3:
        return float("nan")
    return spearman(np.array(a[:n]), np.array(b[:n]))


@dataclass
class CampaignResult:
    factor_id: str
    name: str
    family: str
    status: str
    redundant_with: str | None
    report: FactorReport


class FactorCampaign:
    def __init__(self, db_path: str = "./data/factor_library.duckdb", *,
                 ledger: DoFLedger | None = None, t_min: float = 2.0,
                 redundancy_threshold: float = 0.8) -> None:
        self._path = db_path
        self._in_memory = db_path == ":memory:"
        self._persistent_conn: duckdb.DuckDBPyConnection | None = None
        self._ledger = ledger if ledger is not None else DoFLedger(
            ":memory:" if self._in_memory else "./data/dof_ledger.duckdb")
        self._t_min = t_min
        self._rthr = redundancy_threshold
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
        self._ledger.close()

    def _existing(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT name, family, ls_series FROM factor_evaluations "
                "WHERE status != 'REDUNDANT'"
            ).fetchall()
        return [{"name": r[0], "family": r[1], "ls_series": json.loads(r[2] or "[]")}
                for r in rows]

    def screen_redundancy(self, ls_series: list) -> tuple[str | None, float]:
        """Nearest existing factor by long-short return correlation. Returns
        (name, corr) if any |corr| >= threshold, else (None, best_corr)."""
        best_name, best_abs, best_signed = None, 0.0, 0.0
        for e in self._existing():
            c = _series_corr(ls_series, e["ls_series"])
            if c == c and abs(c) > best_abs:
                best_name, best_abs, best_signed = e["name"], abs(c), c
        if best_name is not None and best_abs >= self._rthr:
            return best_name, best_signed
        return None, best_signed

    def run(self, name: str, family: str,
            signals: list[dict], forward_returns: list[dict],
            *, hypothesis_id: str | None = None, variant: str | None = None,
            dataset_id: str | None = None, period: str | None = None,
            params: dict | None = None, **eval_kwargs) -> CampaignResult:
        rep = evaluate_factor(signals, forward_returns, **eval_kwargs)

        # log the trial so the family's degrees of freedom stay honest
        self._ledger.record(Trial(family=family, hypothesis_id=hypothesis_id,
                                   variant=variant or name, dataset_id=dataset_id,
                                   period=period, params=params or {},
                                   selection_note="factor_campaign"))

        redundant_with, _ = self.screen_redundancy(rep.ls_return_series)
        if redundant_with is not None:
            status = "REDUNDANT"
        elif not (rep.ic_t_stat == rep.ic_t_stat) or abs(rep.ic_t_stat) < self._t_min:
            status = "INSIGNIFICANT"
        else:
            status = "PROMISING"

        factor_id = str(uuid.uuid4())
        fp = _fingerprint(name, family, rep.ls_return_series)
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO factor_evaluations VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [factor_id, name, family, rep.ic_mean, rep.ic_ir, rep.ic_t_stat,
                 rep.ls_sharpe, rep.turnover, status, redundant_with,
                 json.dumps(rep.ls_return_series), fp, datetime.now(UTC)],
            )
        return CampaignResult(factor_id, name, family, status, redundant_with, rep)

    def library(self, *, status: str | None = None) -> list[dict]:
        q = ("SELECT name, family, ic_mean, ic_ir, ic_t_stat, ls_sharpe, turnover, "
             "status, redundant_with FROM factor_evaluations")
        args: list = []
        if status:
            q += " WHERE status = ?"
            args.append(status)
        q += " ORDER BY ic_t_stat DESC"
        with self._conn() as conn:
            rows = conn.execute(q, args).fetchall()
        cols = ["name", "family", "ic_mean", "ic_ir", "ic_t_stat", "ls_sharpe",
                "turnover", "status", "redundant_with"]
        return [dict(zip(cols, r, strict=True)) for r in rows]

    def n_trials(self, family: str) -> int:
        return self._ledger.effective_trials(family)

    def return_series(self, *, status: str = "PROMISING") -> dict:
        """{name: long-short return series} for factors at a given status — the
        independent-edge inputs for ensembling (M37)."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT name, ls_series FROM factor_evaluations WHERE status = ?",
                [status],
            ).fetchall()
        return {r[0]: json.loads(r[1] or "[]") for r in rows}

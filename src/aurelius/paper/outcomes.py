"""Paper-trading outcomes — the loop back from live paper trading to research.

DuckDB-backed, same pattern as ResearchStore. This is the missing link the
Research Director and Intelligence frameworks kept flagging: validation says
"accept", the strategy goes to paper trading, and *this* store records what
actually happened, keyed by the hypothesis that spawned it.

A validation "accept" that later fails in paper trading is a false positive —
the single most important signal for improving the research process. It cannot
be computed until outcomes land here, so this store is the producer seam.

The live/paper system (or an operator) writes outcomes via `record`; the
Intelligence engine reads them. Regime is captured here because the *live*
system knows the prevailing market regime — historical backtests do not persist
their tested window, so regime can only be truthfully attached at paper time.
"""

from __future__ import annotations

import enum
import uuid
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import duckdb

from aurelius.core.logging import get_logger

logger = get_logger(__name__)


class PaperOutcome(enum.StrEnum):
    RUNNING = "running"  # paper trading in progress, no verdict yet
    CONFIRMED = "confirmed"  # live paper results held up — edge is real
    DEGRADED = "degraded"  # weaker than backtest but still positive
    FAILED = "failed"  # edge did not survive live — validation false positive


_CREATE = """
CREATE TABLE IF NOT EXISTS paper_outcomes (
    id               VARCHAR PRIMARY KEY,
    hypothesis_id    VARCHAR NOT NULL,
    strategy_name    VARCHAR NOT NULL,
    recorded_at      TIMESTAMPTZ NOT NULL,
    regime           VARCHAR,          -- bull | bear | high_vol | low_vol | ...
    outcome          VARCHAR NOT NULL, -- running | confirmed | degraded | failed
    paper_sharpe     DOUBLE,
    paper_return     DOUBLE,
    paper_max_drawdown DOUBLE,
    live_days        INTEGER,
    backtest_sharpe  DOUBLE,           -- for decay comparison
    notes            VARCHAR
)
"""


class PaperOutcomeStore:
    def __init__(self, db_path: str = "./data/paper_outcomes.duckdb") -> None:
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

    def record(
        self,
        hypothesis_id: str,
        strategy_name: str,
        outcome: PaperOutcome | str,
        *,
        regime: str | None = None,
        paper_sharpe: float | None = None,
        paper_return: float | None = None,
        paper_max_drawdown: float | None = None,
        live_days: int | None = None,
        backtest_sharpe: float | None = None,
        notes: str = "",
    ) -> str:
        outcome = PaperOutcome(outcome)  # validates the enum at the trust boundary
        oid = str(uuid.uuid4())
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO paper_outcomes VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                [
                    oid,
                    hypothesis_id,
                    strategy_name,
                    datetime.now(UTC),
                    regime,
                    outcome.value,
                    paper_sharpe,
                    paper_return,
                    paper_max_drawdown,
                    live_days,
                    backtest_sharpe,
                    notes,
                ],
            )
        logger.info(
            "paper_outcome_recorded",
            hypothesis_id=hypothesis_id,
            outcome=outcome.value,
            regime=regime,
        )
        return oid

    def all(self) -> list[dict]:
        return self._query("SELECT * FROM paper_outcomes ORDER BY recorded_at", [])

    def for_hypothesis(self, hypothesis_id: str) -> list[dict]:
        return self._query(
            "SELECT * FROM paper_outcomes WHERE hypothesis_id = ? ORDER BY recorded_at",
            [hypothesis_id],
        )

    def latest_per_hypothesis(self) -> list[dict]:
        """Most recent outcome for each hypothesis — the current verdict."""
        return self._query(
            "SELECT * FROM paper_outcomes o WHERE recorded_at = ("
            "  SELECT MAX(recorded_at) FROM paper_outcomes i "
            "  WHERE i.hypothesis_id = o.hypothesis_id) ORDER BY recorded_at DESC",
            [],
        )

    def stats(self) -> dict:
        with self._conn() as conn:
            by_outcome = conn.execute(
                "SELECT outcome, COUNT(*) FROM paper_outcomes GROUP BY outcome"
            ).fetchall()
            total = conn.execute("SELECT COUNT(*) FROM paper_outcomes").fetchone()[0]  # type: ignore[index]
        return {"total": total, "by_outcome": {r[0]: r[1] for r in by_outcome}}

    def _query(self, sql: str, params: list) -> list[dict]:
        with self._conn() as conn:
            res = conn.execute(sql, params)
            cols = [d[0] for d in res.description]
            return [dict(zip(cols, row, strict=False)) for row in res.fetchall()]


if __name__ == "__main__":
    s = PaperOutcomeStore(":memory:")
    s.record(
        "h1",
        "mom_strat",
        PaperOutcome.CONFIRMED,
        regime="bull",
        paper_sharpe=1.1,
        backtest_sharpe=1.3,
    )
    s.record("h1", "mom_strat", "failed", regime="bear", paper_sharpe=-0.2)
    s.record("h2", "mr_strat", PaperOutcome.RUNNING)
    latest = {o["hypothesis_id"]: o["outcome"] for o in s.latest_per_hypothesis()}
    assert latest["h1"] == "failed", latest  # most recent wins
    assert s.stats()["total"] == 3
    try:
        s.record("h3", "x", "not_a_real_outcome")
        raise AssertionError("bad outcome should have raised")
    except ValueError:
        pass
    print("paper outcome store self-check ok:", latest, s.stats())

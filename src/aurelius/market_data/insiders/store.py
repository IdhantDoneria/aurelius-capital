"""Point-in-time insider transaction store (AIDP Phase 5).

Append-only ledger of SEC Form 3/4/5 insider activity. Every row carries three
timestamps; research queries are gated by **acceptance_datetime** (when the
filing became public), never by transaction_date. A trade on Jan 1 filed/accepted
Jan 3 is invisible to a query dated Jan 2.

Amendments (Form 4/A) are appended as new rows (new accession → new
transaction_id); `transactions_as_of` collapses to the latest accepted version
per logical transaction, so restatements win without overwriting history.

Additive: new store (data/insiders.duckdb). Phase 1-4 tables untouched.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from pathlib import Path

import duckdb

from aurelius.core.logging import get_logger

logger = get_logger(__name__)

_CREATE = """
CREATE TABLE IF NOT EXISTS insider_transactions (
    transaction_id      VARCHAR   PRIMARY KEY,
    security_id         VARCHAR,
    cik                 VARCHAR   NOT NULL,
    insider_name        VARCHAR,
    insider_role        VARCHAR,
    insider_type        VARCHAR,                 -- officer|director|tenpercent|other
    transaction_date    DATE,
    filing_date         DATE,
    acceptance_datetime TIMESTAMP NOT NULL,      -- availability gate
    transaction_code    VARCHAR,                 -- P|S|A|M|F|G|...
    shares              DOUBLE,
    price               DOUBLE,
    value               DOUBLE,
    ownership_after     DOUBLE,
    ownership_type      VARCHAR,                 -- direct|indirect
    accession           VARCHAR,
    form_type           VARCHAR,                 -- 3|4|5|4/A|...
    source              VARCHAR,
    vendor              VARCHAR   DEFAULT 'sec_edgar',
    data_version        INTEGER   DEFAULT 1,
    created_at          TIMESTAMP,
    updated_at          TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_ins_pit ON insider_transactions(security_id, acceptance_datetime);
CREATE INDEX IF NOT EXISTS ix_ins_cik ON insider_transactions(cik, acceptance_datetime);
"""

_COLS = (
    "transaction_id", "security_id", "cik", "insider_name", "insider_role", "insider_type",
    "transaction_date", "filing_date", "acceptance_datetime", "transaction_code", "shares",
    "price", "value", "ownership_after", "ownership_type", "accession", "form_type",
    "source", "vendor", "data_version",
)

# logical identity of a transaction (an amendment shares this key, differs by accession)
_LOGICAL_KEY = "cik, insider_name, transaction_date, transaction_code, ownership_type"


def _cutoff(query_time: date | datetime) -> str:
    """Normalize a date/datetime to an inclusive acceptance cutoff. A bare date
    means 'anything accepted through end of that day is known'."""
    if isinstance(query_time, datetime):
        return query_time.isoformat()
    return datetime(query_time.year, query_time.month, query_time.day, 23, 59, 59).isoformat()


class InsiderStore:
    def __init__(self, db_path: str = "./data/insiders.duckdb") -> None:
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

    def write_transactions(self, txns: list[dict]) -> int:
        """Append insider transactions. Idempotent on transaction_id; amendments
        arrive as distinct transaction_ids and are all retained."""
        if not txns:
            return 0
        import pandas as pd

        now = datetime.now(UTC)
        df = pd.DataFrame(
            [{**{c: t.get(c) for c in _COLS},
              "vendor": t.get("vendor", "sec_edgar"),
              "data_version": t.get("data_version", 1)} for t in txns],
            columns=list(_COLS),
        )
        df["created_at"] = now
        df["updated_at"] = now
        cols = ", ".join([*_COLS, "created_at", "updated_at"])
        with self._conn() as conn:
            conn.register("_ins_in", df)
            try:
                conn.execute(
                    f"INSERT OR REPLACE INTO insider_transactions ({cols}) SELECT {cols} FROM _ins_in"
                )
            finally:
                conn.unregister("_ins_in")
        return len(txns)

    def transactions_as_of(self, security_id: str, query_time: date | datetime) -> list[dict]:
        """Transactions for a security that were PUBLICLY KNOWN by `query_time`
        (acceptance_datetime <= cutoff), collapsed to the latest accepted
        amendment per logical transaction. Never gated on transaction_date."""
        cols = ("transaction_id", "insider_name", "insider_role", "insider_type",
                "transaction_date", "filing_date", "acceptance_datetime", "transaction_code",
                "shares", "price", "value", "ownership_after", "ownership_type", "accession", "form_type")
        sel = ", ".join(cols)
        with self._conn() as conn:
            rows = conn.execute(
                f"""SELECT {sel} FROM (
                        SELECT *, ROW_NUMBER() OVER (
                            PARTITION BY {_LOGICAL_KEY} ORDER BY acceptance_datetime DESC
                        ) rn
                        FROM insider_transactions
                        WHERE security_id = ? AND acceptance_datetime <= ?
                    ) t WHERE rn = 1
                    ORDER BY transaction_date, insider_name""",
                [security_id, _cutoff(query_time)],
            ).fetchall()
        return [dict(zip(cols, r, strict=True)) for r in rows]

    def signals_as_of(self, security_ids: list[str], query_time: date | datetime) -> dict[str, dict]:
        """Batch PIT insider aggregates for many securities in ONE query — the
        research/factor path. Same acceptance gate and amendment collapse as
        transactions_as_of, widened by security_id, then aggregated to P/S counts,
        buy/sell value, distinct buyers, and signed ownership change per security.
        Securities with no known transactions are simply absent from the result."""
        if not security_ids:
            return {}
        placeholders = ", ".join("?" * len(security_ids))
        with self._conn() as conn:
            rows = conn.execute(
                f"""SELECT security_id,
                        SUM(CASE WHEN transaction_code = 'P' THEN 1 ELSE 0 END) AS purchases,
                        SUM(CASE WHEN transaction_code = 'S' THEN 1 ELSE 0 END) AS sales,
                        SUM(CASE WHEN transaction_code = 'P' THEN COALESCE(value, 0) ELSE 0 END) AS buy_value,
                        SUM(CASE WHEN transaction_code = 'S' THEN COALESCE(value, 0) ELSE 0 END) AS sell_value,
                        COUNT(DISTINCT CASE WHEN transaction_code = 'P' THEN insider_name END) AS buyers,
                        SUM(CASE WHEN transaction_code IN ('P','S') THEN COALESCE(shares, 0) ELSE 0 END) AS ownership_change
                    FROM (
                        SELECT *, ROW_NUMBER() OVER (
                            PARTITION BY security_id, {_LOGICAL_KEY} ORDER BY acceptance_datetime DESC
                        ) rn
                        FROM insider_transactions
                        WHERE security_id IN ({placeholders}) AND acceptance_datetime <= ?
                    ) t WHERE rn = 1
                    GROUP BY security_id""",
                [*security_ids, _cutoff(query_time)],
            ).fetchall()
        keys = ("purchases", "sales", "buy_value", "sell_value", "buyers", "ownership_change")
        return {r[0]: dict(zip(keys, r[1:], strict=True)) for r in rows}

    def insider_position_as_of(self, security_id: str, insider_name: str,
                               query_time: date | datetime) -> float | None:
        """Reported shares-owned-after for an insider's latest transaction known
        by `query_time`."""
        with self._conn() as conn:
            row = conn.execute(
                """SELECT ownership_after FROM insider_transactions
                   WHERE security_id = ? AND insider_name = ? AND acceptance_datetime <= ?
                   ORDER BY transaction_date DESC, acceptance_datetime DESC LIMIT 1""",
                [security_id, insider_name, _cutoff(query_time)],
            ).fetchone()
        return row[0] if row else None

    def latest_transactions(self, security_id: str, limit: int = 50) -> list[dict]:
        """Most recent transactions by acceptance time (no PIT gate — operational view)."""
        cols = ("transaction_id", "insider_name", "transaction_date", "acceptance_datetime",
                "transaction_code", "shares", "price", "value", "form_type")
        sel = ", ".join(cols)
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT {sel} FROM insider_transactions WHERE security_id = ? "
                f"ORDER BY acceptance_datetime DESC LIMIT ?", [security_id, limit],
            ).fetchall()
        return [dict(zip(cols, r, strict=True)) for r in rows]

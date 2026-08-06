"""PIT price store — corporate-action-aware, point-in-time-correct read path.

Fixes audit findings P1/P2/C1. Additive: coexists with the legacy `ohlcv` table
in DuckDBStore, which holds vendor-adjusted closes and is NOT PIT-safe.

Design:
  raw_ohlcv          immutable RAW (unadjusted) prices as the vendor first
                     reported them. Never restated by later splits.
  corporate_actions  split events with an effective_date AND an announced_date.

A price for a bar at date t, queried "as of" date D, is back-adjusted only by
splits with t < effective_date <= D that were announced <= the knowledge date
(default = D). A split that happens AFTER D therefore cannot touch the price you
see as-of D — no future corporate action leaks into the past.

Dividends: total-return adjustment is a documented next step (splits alone fix
the price-continuity leak the momentum/pairs research hits). See
docs/AIDP_AUDIT_AND_ROADMAP.md.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import duckdb

from aurelius.core.logging import get_logger

logger = get_logger(__name__)

_CREATE = """
CREATE TABLE IF NOT EXISTS raw_ohlcv (
    symbol      VARCHAR       NOT NULL,
    timestamp   TIMESTAMPTZ   NOT NULL,
    frequency   VARCHAR(10)   NOT NULL,
    open        DECIMAL(20,8) NOT NULL,
    high        DECIMAL(20,8) NOT NULL,
    low         DECIMAL(20,8) NOT NULL,
    close       DECIMAL(20,8) NOT NULL,
    volume      DECIMAL(28,4) NOT NULL,
    source      VARCHAR(50),
    PRIMARY KEY (symbol, timestamp, frequency)
);
CREATE TABLE IF NOT EXISTS corporate_actions (
    symbol         VARCHAR     NOT NULL,
    effective_date DATE        NOT NULL,
    kind           VARCHAR(10) NOT NULL,          -- 'split'
    ratio          DECIMAL(18,8) NOT NULL,        -- new:old, e.g. 2.0 for a 2:1 split
    announced_date DATE        NOT NULL,          -- when the action became known
    PRIMARY KEY (symbol, effective_date, kind)
);
"""

_RAW_COLS = ("symbol", "timestamp", "frequency", "open", "high", "low", "close", "volume", "source")


class PitPriceStore:
    """Point-in-time-correct, corporate-action-aware price store."""

    def __init__(self, db_path: str = "./data/analytics.duckdb") -> None:
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

    def write_raw_bars(self, bars: list[dict]) -> int:
        """Insert immutable RAW bars. Idempotent on (symbol, timestamp, frequency).

        Raw prices must never be back-restated by later corporate actions — that
        restatement is the P1 leak. Feed unadjusted vendor prices here.
        """
        if not bars:
            return 0
        import pandas as pd

        df = pd.DataFrame([{c: b.get(c) for c in _RAW_COLS} for b in bars], columns=list(_RAW_COLS))
        cols = ", ".join(_RAW_COLS)
        with self._conn() as conn:
            conn.register("_raw_in", df)
            try:
                conn.execute(f"INSERT OR REPLACE INTO raw_ohlcv ({cols}) SELECT {cols} FROM _raw_in")
            finally:
                conn.unregister("_raw_in")
        return len(bars)

    def record_actions(self, actions: list[dict]) -> int:
        """Record split events. Each: symbol, effective_date, ratio, announced_date."""
        if not actions:
            return 0
        with self._conn() as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO corporate_actions "
                "(symbol, effective_date, kind, ratio, announced_date) VALUES (?, ?, 'split', ?, ?)",
                [
                    [a["symbol"], a["effective_date"], Decimal(str(a["ratio"])), a["announced_date"]]
                    for a in actions
                ],
            )
        return len(actions)

    def close_as_of(
        self, symbol: str, as_of: date, knowledge_date: date | None = None
    ) -> Decimal | None:
        """PIT-correct adjusted close of the latest bar on/before `as_of`.

        Back-adjusted by splits with bar_date < effective_date <= as_of that were
        announced on/before `knowledge_date` (default = as_of). Splits effective
        after as_of are invisible — no future-action leakage.
        """
        knowledge_date = knowledge_date or as_of
        with self._conn() as conn:
            bar = conn.execute(
                """
                SELECT CAST(timestamp AS DATE), close FROM raw_ohlcv
                WHERE symbol = ? AND frequency = '1d' AND CAST(timestamp AS DATE) <= ?
                ORDER BY timestamp DESC LIMIT 1
                """,
                [symbol, as_of.isoformat()],
            ).fetchone()
            if bar is None:
                return None
            bar_date, raw_close = bar[0], Decimal(str(bar[1]))
            splits = conn.execute(
                """
                SELECT ratio FROM corporate_actions
                WHERE symbol = ? AND kind = 'split'
                  AND effective_date > ? AND effective_date <= ? AND announced_date <= ?
                """,
                [symbol, bar_date, as_of.isoformat(), knowledge_date.isoformat()],
            ).fetchall()
        factor = Decimal(1)
        for (ratio,) in splits:
            factor /= Decimal(str(ratio))  # 2:1 split → pre-split prices ×0.5
        return raw_close * factor

    def window_as_of(
        self, symbol: str, as_of: date, lookback_days: int = 252,
        knowledge_date: date | None = None,
    ) -> list[dict]:
        """PIT-adjusted daily bars in (as_of − lookback_days, as_of], each
        back-adjusted into the as_of frame by the same split rule as close_as_of.

        Returns [{date, close, volume}] oldest-first. close is split-adjusted;
        volume is inverse-adjusted so dollar_volume (close×volume) is split-
        invariant. Reuses the certified adjustment logic — no forked math.
        """
        knowledge_date = knowledge_date or as_of
        start = as_of - timedelta(days=lookback_days)
        with self._conn() as conn:
            bars = conn.execute(
                """
                SELECT CAST(timestamp AS DATE), close, volume FROM raw_ohlcv
                WHERE symbol = ? AND frequency = '1d'
                  AND CAST(timestamp AS DATE) <= ? AND CAST(timestamp AS DATE) > ?
                ORDER BY timestamp
                """,
                [symbol, as_of.isoformat(), start.isoformat()],
            ).fetchall()
            if not bars:
                return []
            splits = conn.execute(
                """
                SELECT effective_date, ratio FROM corporate_actions
                WHERE symbol = ? AND kind = 'split'
                  AND effective_date <= ? AND announced_date <= ?
                """,
                [symbol, as_of.isoformat(), knowledge_date.isoformat()],
            ).fetchall()
        out: list[dict] = []
        for bar_date, raw_close, raw_vol in bars:
            factor = Decimal(1)
            for eff, ratio in splits:
                if bar_date < eff:  # split effective after this bar, on/before as_of
                    factor /= Decimal(str(ratio))
            out.append({
                "date": bar_date,
                "close": Decimal(str(raw_close)) * factor,
                "volume": Decimal(str(raw_vol)) / factor,
            })
        return out

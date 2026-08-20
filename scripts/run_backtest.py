"""12-month price momentum (excl. last month) × volume-confirmation backtest, 2020-2024.

Signal: Jegadeesh-Titman (1993) style 12M-1M momentum amplified by volume abnormality.
  score = (close_21d_ago - close_252d_ago) / close_252d_ago
          × clamp(yesterday_vol / 20d_avg_vol, 0.5, 5.0)

  Skipping the last 21 trading days avoids the 1-month short-term reversal effect that
  contaminates pure trailing-return signals (Jegadeesh & Titman 1993).

Portfolio: weekly rebalancing, long-only, top 20%, 40 positions, 2.5% NAV each.

Root-cause fix for 4-year cutoff:
  All signals pre-computed in ONE SQL query before iter_bars() starts.
  Signal fn is pure dict lookup — zero DB connections during the backtest loop.

Usage:
    .venv/bin/python scripts/run_backtest.py
"""

from __future__ import annotations

import sys
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT / "src"))

from mentisrex.backtesting.config import BacktestConfig
from mentisrex.backtesting.data.feed import DuckDBDataFeed, _resolve_connection
from mentisrex.backtesting.engine import BacktestEngine
from mentisrex.backtesting.strategy.cross_sectional import CrossSectionalFactorStrategy
from mentisrex.core.logging import configure_logging

configure_logging(log_level="WARNING", json_logs=False)  # suppress per-fill debug noise

DB_PATH = str(_ROOT / "data" / "analytics.duckdb")

# ── Signal pre-computation ────────────────────────────────────────────────────

_SIGNAL_SQL = """
WITH base AS (
    SELECT
        symbol,
        CAST(timestamp AS DATE)                           AS dt,
        close * adjustment_factor                         AS adj_close,
        volume / NULLIF(adjustment_factor, 0)             AS adj_volume
    FROM ohlcv
    WHERE frequency = '1d'
      AND CAST(timestamp AS DATE) BETWEEN DATE '{warmup}' AND DATE '{end}'
      -- US-listed only: exclude foreign suffixes and CIK-format fundamentals IDs
      AND symbol NOT LIKE '%.NS'
      AND symbol NOT LIKE '%.BO'
      AND symbol NOT LIKE '%.L'
      AND symbol NOT LIKE '%.TO'
      AND symbol NOT LIKE '%.AX'
      AND symbol NOT LIKE 'CIK%'
),
windowed AS (
    SELECT
        symbol,
        dt,
        adj_close,
        adj_volume,
        -- 12M-1M momentum: price 252 days ago and 21 days ago (skip last month)
        LAG(adj_close, 252) OVER (PARTITION BY symbol ORDER BY dt) AS c252,
        LAG(adj_close, 21)  OVER (PARTITION BY symbol ORDER BY dt) AS c21,
        LAG(adj_volume, 1)  OVER (PARTITION BY symbol ORDER BY dt) AS vol_prev,
        AVG(adj_volume)     OVER (
            PARTITION BY symbol ORDER BY dt
            ROWS BETWEEN 25 PRECEDING AND 1 PRECEDING
        )                                                  AS vol_avg20,
        AVG(adj_close * adj_volume) OVER (
            PARTITION BY symbol ORDER BY dt
            ROWS BETWEEN 25 PRECEDING AND 1 PRECEDING
        )                                                  AS avg_dollar_vol
    FROM base
)
SELECT
    symbol,
    dt,
    -- JT-style 12M-1M momentum × volume confirmation
    (c21 - c252) / NULLIF(c252, 0)
    * LEAST(GREATEST(vol_prev / NULLIF(vol_avg20, 0), 0.5), 5.0) AS score
FROM windowed
WHERE dt >= DATE '{start}'
  AND c252           IS NOT NULL
  AND c21            IS NOT NULL
  AND vol_prev       IS NOT NULL
  AND vol_avg20      IS NOT NULL
  AND avg_dollar_vol IS NOT NULL
  AND c252 >= 5.0              -- minimum $5 price (no penny stocks)
  AND adj_close >= 5.0         -- current price also >= $5
  AND avg_dollar_vol >= 500000  -- minimum $500k avg daily dollar volume
ORDER BY dt, symbol
"""

# Short universe: same momentum signal, stricter liquidity (large-caps only)
_SHORT_SIGNAL_SQL = """
WITH base AS (
    SELECT
        symbol,
        CAST(timestamp AS DATE)                           AS dt,
        close * adjustment_factor                         AS adj_close,
        volume / NULLIF(adjustment_factor, 0)             AS adj_volume
    FROM ohlcv
    WHERE frequency = '1d'
      AND CAST(timestamp AS DATE) BETWEEN DATE '{warmup}' AND DATE '{end}'
      AND symbol NOT LIKE '%.NS'
      AND symbol NOT LIKE '%.BO'
      AND symbol NOT LIKE '%.L'
      AND symbol NOT LIKE '%.TO'
      AND symbol NOT LIKE '%.AX'
      AND symbol NOT LIKE 'CIK%'
),
windowed AS (
    SELECT
        symbol, dt, adj_close, adj_volume,
        LAG(adj_close, 252) OVER (PARTITION BY symbol ORDER BY dt) AS c252,
        LAG(adj_close, 21)  OVER (PARTITION BY symbol ORDER BY dt) AS c21,
        LAG(adj_volume, 1)  OVER (PARTITION BY symbol ORDER BY dt) AS vol_prev,
        AVG(adj_volume)     OVER (
            PARTITION BY symbol ORDER BY dt
            ROWS BETWEEN 25 PRECEDING AND 1 PRECEDING
        )                                                  AS vol_avg20,
        AVG(adj_close * adj_volume) OVER (
            PARTITION BY symbol ORDER BY dt
            ROWS BETWEEN 25 PRECEDING AND 1 PRECEDING
        )                                                  AS avg_dollar_vol
    FROM base
)
SELECT symbol, dt,
    (c21 - c252) / NULLIF(c252, 0)
    * LEAST(GREATEST(vol_prev / NULLIF(vol_avg20, 0), 0.5), 5.0) AS score
FROM windowed
WHERE dt >= DATE '{start}'
  AND c252 IS NOT NULL AND c21 IS NOT NULL
  AND vol_prev IS NOT NULL AND vol_avg20 IS NOT NULL
  AND avg_dollar_vol IS NOT NULL
  AND c252 >= 10.0              -- higher floor for shorts ($10 min)
  AND adj_close >= 10.0
  AND avg_dollar_vol >= 5000000  -- $5M ADV — liquid enough to borrow
ORDER BY dt, symbol
"""

# Cross-sectional vol regime: median absolute daily return across all large-cap universe stocks.
# When the average stock swings >2.5%/day (annualized >40%), the market is in panic mode.
# This is a VIX proxy that works without any index data in the DB.
_REGIME_SQL = """
WITH base AS (
    SELECT
        symbol,
        CAST(timestamp AS DATE) AS dt,
        close * adjustment_factor AS adj_close,
        AVG(close * adjustment_factor * volume / NULLIF(adjustment_factor, 0)) OVER (
            PARTITION BY symbol ORDER BY CAST(timestamp AS DATE)
            ROWS BETWEEN 25 PRECEDING AND 1 PRECEDING
        ) AS avg_dollar_vol
    FROM ohlcv
    WHERE frequency = '1d'
      AND CAST(timestamp AS DATE) BETWEEN DATE '{warmup}' AND DATE '{end}'
      AND symbol NOT LIKE '%.NS'
      AND symbol NOT LIKE '%.BO'
      AND symbol NOT LIKE '%.L'
      AND symbol NOT LIKE '%.TO'
      AND symbol NOT LIKE '%.AX'
      AND symbol NOT LIKE 'CIK%'
),
rets AS (
    SELECT dt,
           ABS(adj_close / NULLIF(LAG(adj_close, 1) OVER (PARTITION BY symbol ORDER BY dt), 0) - 1)
               AS abs_ret
    FROM base
    WHERE avg_dollar_vol >= 5000000
),
daily_cs_vol AS (
    SELECT dt,
           AVG(abs_ret) * SQRT(252) AS cs_vol_annualized
    FROM rets
    WHERE abs_ret IS NOT NULL AND abs_ret < 0.5
    GROUP BY dt
    HAVING COUNT(*) >= 50
)
SELECT dt, cs_vol_annualized FROM daily_cs_vol
WHERE dt >= DATE '{start}'
ORDER BY dt
"""


def precompute_signals(db_path: str, start: date, end: date) -> dict[date, dict[str, float]]:
    """One-shot query → dict[date -> {symbol: score}]. No DB connections after this."""
    warmup = start - timedelta(days=400)
    sql = _SIGNAL_SQL.format(warmup=warmup.isoformat(), start=start.isoformat(), end=end.isoformat())
    rows = _run_sql(db_path, sql)
    signals: dict[date, dict[str, float]] = defaultdict(dict)
    for symbol, dt, score in rows:
        if score is not None:
            signals[dt][symbol] = float(score)
    total_pairs = sum(len(v) for v in signals.values())
    print(f"[precompute] {len(signals)} signal dates, {total_pairs:,} (symbol,date) pairs")
    if signals:
        first_dt = min(signals)
        print(f"[precompute] first date={first_dt}, symbols on that date={len(signals[first_dt])}")
    return dict(signals)


def _run_sql(db_path: str, sql: str) -> list:
    conn, parquet_mode = _resolve_connection(db_path, read_only=True)
    try:
        return conn.execute(sql).fetchall()
    finally:
        if not parquet_mode:
            conn.close()


def precompute_short_signals(db_path: str, start: date, end: date) -> dict[date, dict[str, float]]:
    warmup = start - timedelta(days=400)
    sql = _SHORT_SIGNAL_SQL.format(warmup=warmup.isoformat(), start=start.isoformat(), end=end.isoformat())
    rows = _run_sql(db_path, sql)
    signals: dict[date, dict[str, float]] = defaultdict(dict)
    for symbol, dt, score in rows:
        if score is not None:
            signals[dt][symbol] = float(score)
    total = sum(len(v) for v in signals.values())
    print(f"[precompute-short] {len(signals)} signal dates, {total:,} (symbol,date) pairs")
    return dict(signals)


def precompute_regime(db_path: str, start: date, end: date) -> dict[date, bool]:
    """True = low-vol (VIX < 25%), shorts allowed. False = hostile, no shorts."""
    warmup = start - timedelta(days=60)
    sql = _REGIME_SQL.format(warmup=warmup.isoformat(), start=start.isoformat(), end=end.isoformat())
    rows = _run_sql(db_path, sql)
    # Cross-sect vol thresholds: hostile above 50% ann, re-enter below 40%.
    # (Cross-sect vol >> index vol because it includes idiosyncratic moves.)
    # COVID crash: cross-sect vol peaks ~150%+. Normal markets: 25-40%.
    regime: dict[date, bool] = {}
    hostile = False
    for dt, vol in rows:
        if vol >= 0.50:
            hostile = True
        elif vol < 0.40:
            hostile = False
        regime[dt] = not hostile
    low_vol_days = sum(1 for v in regime.values() if v)
    print(f"[precompute-regime] {len(regime)} dates, {low_vol_days} low-vol (shorts OK), "
          f"{len(regime)-low_vol_days} hostile (no shorts)")
    return regime


def print_data_stats(db_path: str) -> None:
    conn, parquet_mode = _resolve_connection(db_path, read_only=True)
    try:
        rows = conn.execute(
            "SELECT YEAR(CAST(timestamp AS DATE)) AS yr, COUNT(*) AS bars,"
            " COUNT(DISTINCT symbol) AS syms "
            "FROM ohlcv WHERE frequency='1d' GROUP BY yr ORDER BY yr"
        ).fetchall()
    finally:
        if not parquet_mode:
            conn.close()
    print("[data] OHLCV rows per year:")
    for yr, bars, syms in rows:
        print(f"  {yr}: {bars:>10,} bars  {syms:>6,} symbols")


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    BACKTEST_START = date(2020, 1, 2)
    BACKTEST_END   = date(2024, 12, 31)

    print_data_stats(DB_PATH)
    print()

    print("[run] Pre-computing long signals (JT 12M-1M momentum)...")
    signals = precompute_signals(DB_PATH, BACKTEST_START, BACKTEST_END)
    print("[run] Pre-computing short signals (large-cap only, ADV ≥ $5M)...")
    short_signals = precompute_short_signals(DB_PATH, BACKTEST_START, BACKTEST_END)
    print("[run] Pre-computing SPY realized-vol regime...")
    regime = precompute_regime(DB_PATH, BACKTEST_START, BACKTEST_END)
    print()

    # Zero DB activity from this point on — no cursor corruption possible
    signal_fn       = lambda d: signals.get(d, {})
    short_signal_fn = lambda d: short_signals.get(d, {})
    regime_fn       = lambda d: regime.get(d, True)  # default True (allow shorts) if date missing

    feed = DuckDBDataFeed(
        db_path=DB_PATH,
        frequency="1d",
        start_date=BACKTEST_START,
        end_date=BACKTEST_END,
    )

    strategy = CrossSectionalFactorStrategy(
        signal_fn=signal_fn,
        short_signal_fn=short_signal_fn,
        regime_fn=regime_fn,
        rebalance_freq="weekly",
        q_long=0.20,                  # top 20% by long score → ~40 longs
        q_short=0.20,                 # bottom 20% of short universe → ~40 shorts
        long_only=False,              # long-short with regime gate
        max_positions=40,
    )

    config = BacktestConfig(
        start_date=BACKTEST_START,
        end_date=BACKTEST_END,
        max_position_pct=Decimal("0.025"),    # 2.5% per name
        max_gross_leverage=Decimal("2.5"),    # 100% long + 100% short + rebalance buffer
        commission_rate=Decimal("0.0005"),    # 5 bps per side
        spread_bps=Decimal("3"),
        max_drawdown_halt=Decimal("0.99"),    # disable circuit breaker — full 4-year run
    )

    print("[run] Starting engine...")
    engine = BacktestEngine(strategy=strategy, data_feed=feed, config=config)
    report = engine.run()
    print(report.summary())


if __name__ == "__main__":
    main()

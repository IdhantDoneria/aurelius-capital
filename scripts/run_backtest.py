"""Volume-momentum cross-sectional strategy backtest, 2020-2024.

Strategy:
  Signal = 20d→5d price momentum × clamp(yesterday_vol / 20d_avg_vol, 0.5, 5.0)
  Daily rebalancing. Long top 15%, short bottom 15%. 50 positions each side.
  Position size: 2% NAV per name (100% gross long + 100% gross short = 2x leverage).

Root-cause fix for 4-year cutoff:
  All signals are pre-computed in ONE SQL query before iter_bars() starts.
  The signal fn is then a pure dict lookup — zero DB connections during the loop.
  This eliminates the DuckDB shared-buffer corruption that stopped the feed at
  ~March 2020 when momentum_signal() opened a new connection per rebalance call.

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
        LAG(adj_close, 5)  OVER (PARTITION BY symbol ORDER BY dt) AS c5,
        LAG(adj_close, 25) OVER (PARTITION BY symbol ORDER BY dt) AS c25,
        LAG(adj_volume, 1) OVER (PARTITION BY symbol ORDER BY dt) AS vol_prev,
        AVG(adj_volume)    OVER (
            PARTITION BY symbol ORDER BY dt
            ROWS BETWEEN 25 PRECEDING AND 1 PRECEDING
        )                                                 AS vol_avg20,
        AVG(adj_close * adj_volume) OVER (
            PARTITION BY symbol ORDER BY dt
            ROWS BETWEEN 25 PRECEDING AND 1 PRECEDING
        )                                                 AS avg_dollar_vol
    FROM base
)
SELECT
    symbol,
    dt,
    (c5 - c25) / NULLIF(c25, 0)
    * LEAST(GREATEST(vol_prev / NULLIF(vol_avg20, 0), 0.5), 5.0) AS score
FROM windowed
WHERE dt >= DATE '{start}'
  AND c5            IS NOT NULL
  AND c25           IS NOT NULL
  AND vol_prev      IS NOT NULL
  AND vol_avg20     IS NOT NULL
  AND avg_dollar_vol IS NOT NULL
  AND c25 >= 5.0              -- minimum $5 price (no penny stocks)
  AND adj_close >= 5.0        -- current price also >= $5
  AND avg_dollar_vol >= 500000 -- minimum $500k avg daily dollar volume
ORDER BY dt, symbol
"""


def precompute_signals(db_path: str, start: date, end: date) -> dict[date, dict[str, float]]:
    """One-shot query → dict[date -> {symbol: score}]. No DB connections after this."""
    # 60 extra calendar days so the 25-bar window is warm by backtest start
    warmup = start - timedelta(days=60)
    sql = _SIGNAL_SQL.format(
        warmup=warmup.isoformat(),
        start=start.isoformat(),
        end=end.isoformat(),
    )
    conn, parquet_mode = _resolve_connection(db_path, read_only=True)
    try:
        rows = conn.execute(sql).fetchall()
    finally:
        if not parquet_mode:
            conn.close()

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

    print("[run] Pre-computing volume-momentum signals...")
    signals = precompute_signals(DB_PATH, BACKTEST_START, BACKTEST_END)
    print()

    # Zero DB activity from this point on — no cursor corruption possible
    signal_fn = lambda d: signals.get(d, {})

    feed = DuckDBDataFeed(
        db_path=DB_PATH,
        frequency="1d",
        start_date=BACKTEST_START,
        end_date=BACKTEST_END,
    )

    strategy = CrossSectionalFactorStrategy(
        signal_fn=signal_fn,
        rebalance_freq="weekly",      # weekly: ~250 rebalances over 4y, high turnover, not HFT
        q_long=0.20,                  # top 20% by score
        long_only=True,               # long-only: survives momentum crashes (COVID)
        max_positions=40,
    )

    config = BacktestConfig(
        start_date=BACKTEST_START,
        end_date=BACKTEST_END,
        max_position_pct=Decimal("0.025"),    # 2.5% per name × 40 = 100% invested
        max_gross_leverage=Decimal("1.3"),    # headroom for rebalancing without rejecting AAPL/AMZN
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

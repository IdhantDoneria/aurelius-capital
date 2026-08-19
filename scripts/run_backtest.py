"""End-to-end backtest example: 12-1 month momentum, long-only, 2020-2024.

Usage:
    .venv/bin/python scripts/run_backtest.py

Data: data/analytics.duckdb (or Parquet fallback at data/parquet/analytics/ohlcv.parquet).
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

# Resolve project root so this runs from any cwd
_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT / "src"))

import duckdb

from mentisrex.backtesting.config import BacktestConfig
from mentisrex.backtesting.data.feed import DuckDBDataFeed
from mentisrex.backtesting.engine import BacktestEngine
from mentisrex.backtesting.strategy.cross_sectional import CrossSectionalFactorStrategy

DB_PATH = str(_ROOT / "data" / "analytics.duckdb")


def momentum_signal(as_of: date) -> dict[str, float]:
    """12-1 month cross-sectional momentum: return from 12m ago to 1m ago."""
    t_minus_1m = as_of - timedelta(days=21)
    t_minus_12m = as_of - timedelta(days=252)

    # read_only=True: signal fn runs concurrently with the feed cursor on the same file
    from mentisrex.backtesting.data.feed import _resolve_connection
    conn, parquet_mode = _resolve_connection(DB_PATH, read_only=True)
    try:
        rows = conn.execute(
            """
            WITH prices AS (
                SELECT symbol,
                    -- arg_max returns close at the LATEST timestamp <= target date,
                    -- not the MAX price. This is the actual 1-month-ago close.
                    arg_max(close, timestamp) FILTER (
                        WHERE CAST(timestamp AS DATE) <= ?
                    ) AS close_1m,
                    arg_max(close, timestamp) FILTER (
                        WHERE CAST(timestamp AS DATE) <= ?
                    ) AS close_12m
                FROM ohlcv
                WHERE frequency = '1d'
                  AND CAST(timestamp AS DATE) BETWEEN ? AND ?
                GROUP BY symbol
            )
            SELECT symbol, (close_1m - close_12m) / NULLIF(close_12m, 0) AS momentum
            FROM prices
            WHERE close_1m IS NOT NULL AND close_12m IS NOT NULL AND close_12m != 0
            """,
            [t_minus_1m.isoformat(), t_minus_12m.isoformat(),
             t_minus_12m.isoformat(), t_minus_1m.isoformat()],
        ).fetchall()
    except Exception:
        return {}
    finally:
        if not parquet_mode:
            conn.close()

    return {row[0]: float(row[1]) for row in rows if row[1] is not None}


def main() -> None:
    feed = DuckDBDataFeed(
        db_path=DB_PATH,
        frequency="1d",
        start_date=date(2019, 1, 1),   # extra year for warm-up
        end_date=date(2024, 12, 31),
    )

    strategy = CrossSectionalFactorStrategy(
        signal_fn=momentum_signal,
        rebalance_freq="monthly",
        q_long=0.2,
        long_only=True,
        max_positions=50,
    )

    config = BacktestConfig(
        start_date=date(2020, 1, 1),
        end_date=date(2024, 12, 31),
    )

    engine = BacktestEngine(strategy=strategy, data_feed=feed, config=config)
    report = engine.run()
    print(report.summary())


if __name__ == "__main__":
    main()

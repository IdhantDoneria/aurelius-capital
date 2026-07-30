#!/usr/bin/env python
"""Load sample market data through the real ingestion path, then execute the
first momentum experiment.

Pipeline (market-data-ingestion components only — no Postgres, no new framework):
    CSVLoader.load_file  ->  RawBar
    RawBar (as dicts)    ->  DuckDBStore.write_bars   (data/analytics.duckdb)
    DuckDBStore.ohlcv    ->  BarData
    ResearchRunner.investigate(MomentumStrategy)  ->  verdict

    python scripts/load_and_run_momentum.py
"""
from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from aurelius.backtesting.data.feed import BarData
from aurelius.hypothesis.store import HypothesisStore
from aurelius.market_data.adapters.csv_loader import CSVLoader
from aurelius.market_data.storage.duckdb_store import DuckDBStore
from aurelius.research.runner import ResearchRunner, research_config
from aurelius.research.store import ResearchStore
from aurelius.research.templates import MomentumStrategy

CSV = Path("data/market_data/sample_momentum_universe.csv")
STORE_DB = "./data/analytics.duckdb"


def load_csv_into_store(store: DuckDBStore) -> int:
    bars = CSVLoader().load_file(CSV, frequency="1d")
    dicts = [
        {
            "symbol": b.symbol, "timestamp": b.timestamp, "frequency": b.frequency,
            "open": b.open, "high": b.high, "low": b.low, "close": b.close,
            "volume": b.volume, "vwap": b.vwap, "trade_count": b.trade_count,
            "quality_score": None, "source": b.source,
        }
        for b in bars
    ]
    return store.write_bars(dicts)


def verify_store(store: DuckDBStore) -> None:
    print("\n── Store verification ──")
    q = store.query(
        "SELECT COUNT(*) n, COUNT(DISTINCT symbol) syms, "
        "MIN(timestamp) lo, MAX(timestamp) hi FROM ohlcv"
    )[0]
    print(f"  rows={q['n']}  securities={q['syms']}  range={q['lo'].date()}..{q['hi'].date()}")
    for row in store.quality_summary()[:3]:
        print(f"    {row['symbol']}: bars={row['bar_count']} {row['earliest'].date()}..{row['latest'].date()}")


def store_to_bars(store: DuckDBStore) -> list[BarData]:
    rows = store.query(
        "SELECT symbol, timestamp, open, high, low, close, volume, frequency "
        "FROM ohlcv WHERE frequency='1d' ORDER BY timestamp, symbol"
    )
    return [
        BarData(
            symbol=r["symbol"], timestamp=r["timestamp"],
            open=Decimal(str(r["open"])), high=Decimal(str(r["high"])),
            low=Decimal(str(r["low"])), close=Decimal(str(r["close"])),
            volume=Decimal(str(r["volume"])), frequency=r["frequency"],
        )
        for r in rows
    ]


def top_momentum_hypothesis() -> tuple[str, str]:
    hs = HypothesisStore()
    cands = hs.search(query="momentum", limit=20)
    for h in cands:
        if h.status != "Rejected" and "momentum" in h.testable_statement.lower():
            return h.testable_statement, (h.economic_intuition or "momentum persistence")
    return (
        "IF 12-1 month momentum is positive THEN forward returns are positive AMONG equities OVER 1_month",
        "Cross-sectional momentum persistence (Jegadeesh-Titman).",
    )


def main() -> None:
    store = DuckDBStore(STORE_DB)

    n = load_csv_into_store(store)
    print(f"Loader imported {n} bars into {STORE_DB}")
    verify_store(store)

    bars = store_to_bars(store)
    stmt, rationale = top_momentum_hypothesis()

    research = ResearchStore()
    runner = ResearchRunner(research)
    h = runner.hypothesis(statement=stmt, rationale=rationale, researcher="research_ops")

    print("\n── Executing momentum experiment ──")
    print(f"  hypothesis: {stmt[:70]}")
    report = runner.investigate(
        hypothesis=h,
        factory_from_params=lambda p: MomentumStrategy(allow_short=False, **p),
        base_params={"lookback": 90, "entry": 0.0},
        bars=bars,
        config=research_config(),
        param_grid={"lookback": [60, 90, 120], "entry": [0.0, 0.02]},
        features_used=["momentum_12_1"],
    )

    print("\n── Verdict ──")
    print(f"  IS Sharpe   : {report.is_sharpe:.3f}")
    print(f"  OOS Sharpe  : {report.oos_sharpe:.3f}")
    print(f"  OOS return  : {report.oos_return:.2%}")
    print(f"  OOS max DD  : {report.oos_max_drawdown:.2%}")
    print(f"  OOS trades  : {report.oos_trades}")
    print(f"  trials      : {report.n_trials}")
    print(f"  adj p-value : {report.adjusted_pvalue:.3f}")
    print(f"  VERDICT     : {report.verdict.value.upper()}")
    for r in report.reasons:
        print(f"    - {r}")
    research.close()
    store.close()


if __name__ == "__main__":
    main()

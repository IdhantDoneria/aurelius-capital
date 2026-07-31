#!/usr/bin/env python
"""US-scoped execution of the existing JT (1993) reproduction.

Reuses the committed implementation VERBATIM — same FactorStrategy, same
jt_params, same ResearchRunner / IS-OOS split. The ONLY difference from
scripts/reproduce_jegadeesh_titman.py is the load universe: US equities only
(symbols with no exchange-suffix dot), because the newly ingested
analytics.duckdb holds BOTH US (1016) and India (1127) names and a faithful
US reproduction must not blend a cross-currency cross-section.

No tuning, no grid, single run.

    python scripts/run_jt_us_reproduction.py
"""
from __future__ import annotations

import sys
import time
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from aurelius.backtesting.data.feed import BarData
from aurelius.market_data.storage.duckdb_store import DuckDBStore
from aurelius.market_data.storage.isolation import validated_universe_filter
from aurelius.research.runner import ResearchRunner, research_config
from aurelius.research.store import ResearchStore
from aurelius.research.templates import FactorStrategy

STORE_DB = "./data/analytics.duckdb"
# US universe = symbols with no exchange suffix (India names carry .NS / .BO).
# G2: validated_universe_filter admits only symbols with adequate history, so
# truncated toy residue (the old 520-bar synthetic series) is excluded on a
# principled data-quality basis rather than a hardcoded ticker blacklist.
US_FILTER = validated_universe_filter("frequency='1d' AND symbol NOT LIKE '%.%'")


def load_us_bars() -> list[BarData]:
    store = DuckDBStore(STORE_DB)
    rows = store.query(
        "SELECT symbol,timestamp,open,high,low,close,volume,frequency "
        f"FROM ohlcv WHERE {US_FILTER} ORDER BY timestamp,symbol"
    )
    store.close()
    return [
        BarData(
            symbol=r["symbol"], timestamp=r["timestamp"],
            open=Decimal(str(r["open"])), high=Decimal(str(r["high"])),
            low=Decimal(str(r["low"])), close=Decimal(str(r["close"])),
            volume=Decimal(str(r["volume"])), frequency=r["frequency"],
        )
        for r in rows
    ]


def main() -> None:
    t0 = time.time()
    bars = load_us_bars()
    t_load = time.time() - t0
    syms = sorted({b.symbol for b in bars})
    ts = sorted({b.timestamp for b in bars})
    print(f"UNIVERSE: US only  |  {len(bars)} bars  {len(syms)} securities  "
          f"{ts[0].date()}..{ts[-1].date()}  (load {t_load:.1f}s)\n")

    # IDENTICAL to committed reproduce_jegadeesh_titman.py — JT 6-6, no tuning.
    jt_params = {"lookback": 126, "quantile": 0.1, "rebalance_days": 21, "allow_short": True}

    store = ResearchStore()
    runner = ResearchRunner(store)
    h = runner.hypothesis(
        statement="Past 6-month winners outperform past 6-month losers over the next 6 months (JT 1993).",
        rationale="Underreaction to information -> relative-strength momentum persists 3-12 months.",
        researcher="reproduction_program_us",
    )
    print(f"Executing FactorStrategy (cross-sectional momentum), JT params: {jt_params}\n")
    t1 = time.time()
    report = runner.investigate(
        hypothesis=h,
        factory_from_params=lambda p: FactorStrategy(**p),
        base_params=jt_params,
        bars=bars,
        config=research_config(),
        param_grid=None,
        features_used=["mom_6m_relative_strength"],
    )
    t_run = time.time() - t1

    print("REPRODUCED RESULT — US universe (IS/OOS 70/30 chronological split)")
    print(f"  IS Sharpe   : {report.is_sharpe:.3f}")
    print(f"  OOS Sharpe  : {report.oos_sharpe:.3f}")
    print(f"  OOS return  : {report.oos_return:.2%}  (winner-minus-loser, zero-cost)")
    print(f"  OOS max DD  : {report.oos_max_drawdown:.2%}")
    print(f"  OOS trades  : {report.oos_trades}")
    print(f"  trials      : {report.n_trials}  (=1, no tuning)")
    print(f"  adj p-value : {report.adjusted_pvalue:.3f}")
    print(f"  verdict     : {report.verdict.value.upper()}")
    print(f"\nRUNTIME: load {t_load:.1f}s  backtest {t_run:.1f}s  total {time.time()-t0:.1f}s")
    store.close()


if __name__ == "__main__":
    main()

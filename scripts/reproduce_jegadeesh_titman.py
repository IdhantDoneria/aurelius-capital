#!/usr/bin/env python
"""Institutional Reproduction Program — Jegadeesh & Titman (1993).

Builds a reproduction queue over the corpus, ranks by data availability /
complexity / reproducibility / effort, selects the highest-priority paper
executable on the AVAILABLE data (daily equity OHLCV), and runs a FAITHFUL
reproduction — no parameter tuning, single JT 6-6 design.

Faithful template = FactorStrategy (cross-sectional decile long-short momentum),
NOT the time-series MomentumStrategy. JT rank stocks by J-month past return,
long top decile / short bottom decile, hold K months.

    python scripts/reproduce_jegadeesh_titman.py
"""
from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from mentisrex.backtesting.data.feed import BarData
from mentisrex.research.runner import ResearchRunner, research_config
from mentisrex.research.store import ResearchStore
from mentisrex.research.templates import FactorStrategy
from mentisrex.market_data.storage.duckdb_store import DuckDBStore

STORE_DB = "./data/analytics.duckdb"

# Reproduction queue: (paper, data_avail, complexity, reproducibility, effort, executable_now, note)
QUEUE = [
    ("Jegadeesh-Titman 1993 (momentum)", "HIGH", "LOW", "HIGH", "LOW", True,
     "prices only; FactorStrategy = exact cross-sectional decile long-short"),
    ("Gatev et al. (pairs trading)", "HIGH", "MED", "MED", "MED", True,
     "prices only; PairsStrategy exists, needs pair-selection step"),
    ("Sharpe 1964 (CAPM)", "PARTIAL", "MED", "MED", "MED", False,
     "equilibrium theory; needs market portfolio + cross-section betas, no L/S strategy"),
    ("Asness et al. (Value & Momentum)", "PARTIAL", "HIGH", "MED", "HIGH", False,
     "momentum leg runnable; value leg needs fundamentals (absent)"),
    ("Fama-French 1993 (3-factor)", "LOW", "MED", "MED", "HIGH", False,
     "needs size + book-to-market from Compustat (absent)"),
    ("Novy-Marx 2013 (gross profitability)", "LOW", "MED", "MED", "HIGH", False,
     "needs gross profitability from Compustat (absent)"),
    ("Carhart 1997 (4-factor / funds)", "LOW", "MED", "LOW", "HIGH", False,
     "needs mutual-fund returns + FF factors (absent)"),
    ("Black-Litterman 1992 (BL optimizer)", "LOW", "HIGH", "LOW", "HIGH", False,
     "portfolio-construction theory; needs equilibrium returns + views (absent)"),
]


def print_queue() -> None:
    print("REPRODUCTION QUEUE (ranked)\n")
    print(f"{'#':>2} {'paper':38s} {'data':7s} {'cplx':4s} {'repro':5s} {'eff':4s} exec")
    for i, (p, d, c, r, e, ok, _note) in enumerate(QUEUE, 1):
        print(f"{i:>2} {p:38s} {d:7s} {c:4s} {r:5s} {e:4s} {'YES' if ok else 'no'}")
    print()


def load_bars() -> list[BarData]:
    store = DuckDBStore(STORE_DB)
    rows = store.query(
        "SELECT symbol,timestamp,open,high,low,close,volume,frequency "
        "FROM ohlcv WHERE frequency='1d' ORDER BY timestamp,symbol"
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
    print_queue()
    selected = QUEUE[0]
    print(f"SELECTED: {selected[0]}\n  reason: {selected[6]}\n")

    bars = load_bars()
    syms = sorted({b.symbol for b in bars})
    ts = sorted({b.timestamp for b in bars})
    print(f"Data: {len(bars)} bars, {len(syms)} securities, {ts[0].date()}..{ts[-1].date()}\n")

    # JT 6-6 design mapped to daily bars. NO tuning: one param set, no grid.
    #   formation J=6 months  ~ 126 trading days lookback
    #   holding   K=6 months  ~ monthly rebalance (21d)
    #   deciles: quantile 0.1 (top/bottom decile), long-short zero-cost
    jt_params = {"lookback": 126, "quantile": 0.1, "rebalance_days": 21, "allow_short": True}

    store = ResearchStore()
    runner = ResearchRunner(store)
    h = runner.hypothesis(
        statement="Past 6-month winners outperform past 6-month losers over the next 6 months (JT 1993).",
        rationale="Underreaction to information → relative-strength momentum persists 3-12 months.",
        researcher="reproduction_program",
    )
    print(f"Executing FactorStrategy (cross-sectional momentum), JT params: {jt_params}\n")
    report = runner.investigate(
        hypothesis=h,
        factory_from_params=lambda p: FactorStrategy(**p),
        base_params=jt_params,
        bars=bars,
        config=research_config(),
        param_grid=None,          # faithful reproduction — no parameter search
        features_used=["mom_6m_relative_strength"],
    )

    print("REPRODUCED RESULT (out-of-sample slice of the loaded universe)")
    print(f"  IS Sharpe   : {report.is_sharpe:.3f}")
    print(f"  OOS Sharpe  : {report.oos_sharpe:.3f}")
    print(f"  OOS return  : {report.oos_return:.2%}  (winner-minus-loser, zero-cost)")
    print(f"  OOS max DD  : {report.oos_max_drawdown:.2%}")
    print(f"  OOS trades  : {report.oos_trades}")
    print(f"  trials      : {report.n_trials}  (=1, no tuning)")
    print(f"  adj p-value : {report.adjusted_pvalue:.3f}")
    print(f"  verdict     : {report.verdict.value.upper()}")
    store.close()


if __name__ == "__main__":
    main()

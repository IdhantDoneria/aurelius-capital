#!/usr/bin/env python
"""M9 engine-path isolation — forensic, config switches only.

The M7 blow-up class reproduces cheaply and deterministically on a fixed, severely
shrunk US universe (M8: 5% subsample, ~50 names, decile ~5). Universe COMPOSITION is
frozen (same deterministic subset every rebalance) so the composition-drift channel
is already removed — yet the baseline still blows up, isolating the remaining
channels. Here we toggle the two config-level switches that touch NO frozen surface:

  * construction : baseline (0.75/_count) vs invariant (M8 bounded equal-weight)
  * cap          : 1.5x gross (ON, production) vs 1000x (effectively OFF)

`max_gross_leverage` and `invariant_construction` are BacktestConfig / strategy
inputs — no engine, signal, factor, cost, or reporting code changes. Full-sample
run_backtest (forensic, not a 70/30 gate). ~seconds (50 names).

    python scripts/run_m9_isolation.py
Output: campaign/momentum/m9/m9_isolation.json (+ printed table)
"""
from __future__ import annotations

import json
import sys
import time
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import duckdb

from mentisrex.backtesting.data.feed import BarData
from mentisrex.market_data.storage.isolation import validated_universe_filter
from mentisrex.research.validation import run_backtest
from mentisrex.research.runner import research_config
from mentisrex.research.templates import FactorStrategy

STORE_DB = "./data/analytics.duckdb"
US_PRED = "frequency='1d' AND symbol NOT LIKE '%.%'"
FRACTION = 0.05
BASE = {"lookback": 126, "quantile": 0.10, "rebalance_days": 21, "allow_short": True,
        "equal_weight": True, "min_price": 5.0, "skip": 21}


def universe(frac: float) -> set[str]:
    conn = duckdb.connect(STORE_DB, read_only=True)
    pred = validated_universe_filter(US_PRED)
    syms = sorted(r[0] for r in conn.execute(
        f"SELECT DISTINCT symbol FROM ohlcv WHERE {pred}").fetchall())
    conn.close()
    n = len(syms)
    target = max(3, int(frac * n))
    idx = [round(i * n / target) for i in range(target)]
    return {syms[min(j, n - 1)] for j in idx}


def load_bars(subset: set[str]) -> list[BarData]:
    conn = duckdb.connect(STORE_DB, read_only=True)
    pred = validated_universe_filter(US_PRED)
    cur = conn.execute(
        "SELECT symbol,timestamp,open,high,low,close,volume,frequency "
        f"FROM ohlcv WHERE {pred} ORDER BY timestamp,symbol")
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r, strict=False)) for r in cur.fetchall() if r[0] in subset]
    conn.close()
    return [BarData(symbol=r["symbol"], timestamp=r["timestamp"],
                    open=Decimal(str(r["open"])), high=Decimal(str(r["high"])),
                    low=Decimal(str(r["low"])), close=Decimal(str(r["close"])),
                    volume=Decimal(str(r["volume"])), frequency=r["frequency"])
            for r in rows]


def start_date_spread(bars: list[BarData]) -> dict:
    """Async-vintage observable: dispersion of per-symbol first bar dates. A wide
    spread => symbols hit the per-symbol rebalance gate on different calendar dates
    (async vintages), the mechanism the engine cannot avoid under the frozen gate."""
    firsts = {}
    for b in bars:
        d = b.timestamp.date()
        if b.symbol not in firsts or d < firsts[b.symbol]:
            firsts[b.symbol] = d
    ds = sorted(firsts.values())
    return {"n_symbols": len(ds), "earliest": str(ds[0]), "latest": str(ds[-1]),
            "distinct_start_dates": len(set(ds))}


def main() -> None:
    out = Path("campaign/momentum/m9/m9_isolation.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    subset = universe(FRACTION)
    bars = load_bars(subset)
    sds = start_date_spread(bars)
    print(f"[m9] fixed {FRACTION:.0%} universe {sds['n_symbols']} names  {len(bars)} bars  "
          f"load {time.time()-t0:.1f}s", flush=True)
    print(f"[m9] async-vintage observable: {sds['distinct_start_dates']} distinct start "
          f"dates, {sds['earliest']}..{sds['latest']}\n", flush=True)

    records = []
    hdr = (f"{'construction':>12} {'cap':>6} {'ret':>9} {'cagr':>8} {'sharpe':>7} "
           f"{'sortino':>8} {'maxDD':>8} {'vol':>7} {'trades':>7} {'turnover':>9}")
    print(hdr); print("-" * len(hdr))
    for construction in ("baseline", "invariant"):
        for cap in ("1.5", "1000"):
            params = dict(BASE, invariant_construction=(construction == "invariant"))
            cfg = research_config(max_position_pct=Decimal("1.0"),
                                  max_gross_leverage=Decimal(cap))
            m = run_backtest(lambda p=params: FactorStrategy(**p), bars, cfg)
            r = {"construction": construction, "cap": cap,
                 "total_return": round(m.total_return, 4), "cagr": round(m.cagr, 4),
                 "sharpe": round(m.sharpe_ratio, 4), "sortino": round(m.sortino_ratio, 4),
                 "max_drawdown": round(m.max_drawdown, 4),
                 "volatility": round(m.annualized_volatility, 4),
                 "num_trades": m.num_trades, "annual_turnover": round(m.annual_turnover, 4)}
            records.append(r)
            print(f"{construction:>12} {cap:>6} {r['total_return']:>9.4f} {r['cagr']:>8.4f} "
                  f"{r['sharpe']:>7.3f} {r['sortino']:>8.3f} {r['max_drawdown']:>8.4f} "
                  f"{r['volatility']:>7.3f} {r['num_trades']:>7} {r['annual_turnover']:>9.3f}",
                  flush=True)
        print()

    out.write_text(json.dumps({"universe": sds, "cells": records}, indent=2) + "\n")
    print(f"Output: {out}   total {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()

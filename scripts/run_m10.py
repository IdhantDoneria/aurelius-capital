#!/usr/bin/env python
"""M10 deployability run — one config per invocation, full-sample economics.

Corrected strategy (M4 + M8 invariant construction) under one deployability config.
Only execution assumptions / liquidity / cost vary; signal/factor/construction-rule/
data frozen. `run_backtest` full-sample → all PerformanceMetrics.

    python scripts/run_m10.py <label> <outfile.jsonl>

Labels (config table below): turnover_{21,28,42,84}, liq_{0,25,50,75},
cost_{gross,low,mid,high}. Writes one jsonl record.
"""
from __future__ import annotations

import json
import sys
import time
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import duckdb

from aurelius.backtesting.data.feed import BarData
from aurelius.market_data.storage.isolation import validated_universe_filter
from aurelius.research.runner import research_config
from aurelius.research.templates import FactorStrategy
from aurelius.research.validation import run_backtest

STORE_DB = "./data/analytics.duckdb"
US_PRED = "frequency='1d' AND symbol NOT LIKE '%.%'"
BASE = dict(lookback=126, quantile=0.10, rebalance_days=21, allow_short=True,
            equal_weight=True, min_price=5.0, skip=21, invariant_construction=True)

# label -> (strategy param overrides, cost overrides bps [comm, spread, slip])
DEFAULT_COST = (10, 5, 10)  # research_config production default
CONFIGS = {
    # Phase 1 — turnover via rebalance cadence (execution assumption)
    "turnover_21": (dict(rebalance_days=21), DEFAULT_COST),
    "turnover_28": (dict(rebalance_days=28), DEFAULT_COST),
    "turnover_42": (dict(rebalance_days=42), DEFAULT_COST),
    "turnover_84": (dict(rebalance_days=84), DEFAULT_COST),
    # Phase 2 — liquidity buckets (median dollar-volume screen + invariant constr.)
    "liq_0":  (dict(liquidity_filter=False), DEFAULT_COST),
    "liq_25": (dict(liquidity_filter=True, liquidity_metric="dollar_volume_median",
                    liquidity_pct=0.25, liquidity_window=21), DEFAULT_COST),
    "liq_50": (dict(liquidity_filter=True, liquidity_metric="dollar_volume_median",
                    liquidity_pct=0.50, liquidity_window=21), DEFAULT_COST),
    "liq_75": (dict(liquidity_filter=True, liquidity_metric="dollar_volume_median",
                    liquidity_pct=0.75, liquidity_window=21), DEFAULT_COST),
    # Phase 4 — cost integration (config-only; comm/spread/slippage bps)
    "cost_gross": (dict(), (0, 0, 0)),
    "cost_low":   (dict(), (5, 5, 10)),
    "cost_mid":   (dict(), (10, 10, 25)),
    "cost_high":  (dict(), (20, 20, 50)),
}


def load_bars() -> list[BarData]:
    pred = validated_universe_filter(US_PRED)
    conn = duckdb.connect(STORE_DB, read_only=True)
    cur = conn.execute(
        "SELECT symbol,timestamp,open,high,low,close,volume,frequency "
        f"FROM ohlcv WHERE {pred} ORDER BY timestamp,symbol")
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r, strict=False)) for r in cur.fetchall()]
    conn.close()
    return [BarData(symbol=r["symbol"], timestamp=r["timestamp"],
                    open=Decimal(str(r["open"])), high=Decimal(str(r["high"])),
                    low=Decimal(str(r["low"])), close=Decimal(str(r["close"])),
                    volume=Decimal(str(r["volume"])), frequency=r["frequency"])
            for r in rows]


def main() -> None:
    label, outfile = sys.argv[1], Path(sys.argv[2])
    outfile.parent.mkdir(parents=True, exist_ok=True)
    sp_over, (comm, spread, slip) = CONFIGS[label]
    params = dict(BASE, **sp_over)

    t0 = time.time()
    bars = load_bars()
    cfg = research_config(
        max_position_pct=Decimal("1.0"),
        commission_rate=Decimal(comm) / Decimal(10000),
        spread_bps=Decimal(spread), slippage_impact_bps=Decimal(slip))
    print(f"[m10:{label}] {len(bars)} bars  {len({b.symbol for b in bars})} names  "
          f"cost {comm}/{spread}/{slip}bps  load {time.time()-t0:.1f}s", flush=True)

    t1 = time.time()
    m = run_backtest(lambda: FactorStrategy(**params), bars, cfg)
    rec = {"label": label, "params": params, "cost_bps": {"comm": comm, "spread": spread,
           "slippage": slip}, "total_return": round(m.total_return, 4),
           "cagr": round(m.cagr, 4), "sharpe": round(m.sharpe_ratio, 4),
           "sortino": round(m.sortino_ratio, 4), "max_drawdown": round(m.max_drawdown, 4),
           "volatility": round(m.annualized_volatility, 4), "num_trades": m.num_trades,
           "annual_turnover": round(m.annual_turnover, 4),
           "avg_holding_days": round(m.avg_holding_period_days, 2),
           "win_rate": round(m.win_rate, 4), "runtime_s": round(time.time() - t1, 1)}
    outfile.write_text(json.dumps(rec) + "\n")
    print(f"[m10:{label}] {json.dumps(rec)}", flush=True)


if __name__ == "__main__":
    main()

#!/usr/bin/env python
"""M3 methodology fidelity run — JT overlapping K-cohort portfolio.

M3 builds on M2 (equal-weight + price screen) and adds JT-1993's overlapping
portfolio structure: K=6 cohorts, each rebalancing every K*period=126 bars
(6 months), exactly one updated per monthly period. The portfolio carries 6
overlapping vintages at any time.

    python scripts/run_m3_jt.py

Output: campaign/momentum/m3/us_jt_m3.jsonl
Prints M2 → M3 side-by-side comparison.
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
from aurelius.research.runner import ResearchRunner, research_config
from aurelius.research.store import ResearchStore
from aurelius.research.templates import OverlappingFactorStrategy

STORE_DB = "./data/analytics.duckdb"
US_PRED = "frequency='1d' AND symbol NOT LIKE '%.%'"

# M2 result (baseline for M3 comparison)
M2 = {
    "oos_sharpe": 0.098, "oos_return": -0.2379, "oos_max_drawdown": -0.7578,
    "oos_trades": 672, "adjusted_pvalue": 0.4244, "verdict": "reject",
}


def load_bars() -> list[BarData]:
    pred = validated_universe_filter(US_PRED)
    conn = duckdb.connect(STORE_DB, read_only=True)
    cur = conn.execute(
        "SELECT symbol,timestamp,open,high,low,close,volume,frequency "
        f"FROM ohlcv WHERE {pred} ORDER BY timestamp,symbol"
    )
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r, strict=False)) for r in cur.fetchall()]
    conn.close()
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
    out = Path("campaign/momentum/m3/us_jt_m3.jsonl")
    out.parent.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    bars = load_bars()
    ts = sorted({b.timestamp for b in bars})
    syms = sorted({b.symbol for b in bars})
    print(f"[m3] {len(bars)} bars  {len(syms)} securities  "
          f"{ts[0].date()}..{ts[-1].date()}  load {time.time()-t0:.1f}s", flush=True)

    # M3 = M2 + overlapping K=6 cohorts (JT-1993 structure)
    params = {
        "K": 6,
        "lookback": 126,
        "rebalance_days": 21,
        "quantile": 0.10,
        "allow_short": True,
        "equal_weight": True,
        "min_price": 5.0,
    }
    cfg = research_config(max_position_pct=Decimal("1.0"))

    store = ResearchStore("./data/research_m3_jt.duckdb")
    runner = ResearchRunner(store)
    h = runner.hypothesis(
        statement="JT 6-1-6 decile (US, M3 overlapping cohorts): K=6 overlapping "
                  "vintages reduce turnover and smooth return distribution per JT-1993.",
        rationale="JT forms K=6 overlapping portfolios held 6 months, rolling 1/6 "
                  "each month. M3 replicates this: one cohort updates each period, "
                  "net signal = majority vote across K cohorts. M2 (price screen) retained.",
        researcher="m3_methodology_campaign",
    )
    t1 = time.time()
    r = runner.investigate(
        hypothesis=h,
        factory_from_params=lambda p: OverlappingFactorStrategy(**p),
        base_params=params,
        bars=bars,
        config=cfg,
        param_grid=None,
        features_used=["mom_relative_strength", "price_screen_jt2001",
                        "overlapping_cohorts_jt1993"],
    )
    rec = {
        "label": "JT_6-1-6_decile_m3",
        "params": params,
        "is_sharpe": round(r.is_sharpe, 4),
        "oos_sharpe": round(r.oos_sharpe, 4),
        "oos_return": round(r.oos_return, 4),
        "oos_max_drawdown": round(r.oos_max_drawdown, 4),
        "oos_trades": r.oos_trades,
        "adjusted_pvalue": round(r.adjusted_pvalue, 4),
        "verdict": r.verdict.value,
        "runtime_s": round(time.time() - t1, 1),
    }
    out.write_text(json.dumps(rec) + "\n")
    store.close()

    print(f"\n{'Metric':<22} {'M3 (overlapping)':>22} {'M2 baseline':>20}")
    print("-" * 66)
    for k, m2_v in [
        ("oos_sharpe", M2["oos_sharpe"]),
        ("oos_return", M2["oos_return"]),
        ("oos_max_drawdown", M2["oos_max_drawdown"]),
        ("oos_trades", M2["oos_trades"]),
        ("adjusted_pvalue", M2["adjusted_pvalue"]),
        ("verdict", M2["verdict"]),
    ]:
        m3_v = rec[k]
        print(f"  {k:<20} {m3_v!r:>22}  vs  {m2_v!r:>15}")
    print(f"\nM3 runtime: {rec['runtime_s']:.0f}s  total: {time.time()-t0:.0f}s")
    print(f"Output: {out}")


if __name__ == "__main__":
    main()

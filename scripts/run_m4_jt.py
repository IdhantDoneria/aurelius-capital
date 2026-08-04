#!/usr/bin/env python
"""M4 methodology fidelity run — JT one-month skip period.

M4 builds on M2 (equal-weight + $5 price screen) and adds JT-1993's one-month
skip: the formation window ends `skip` bars (1 month ≈ 21 trading days) BEFORE
the holding period begins. This removes the short-term (1-month) reversal that
contaminates the momentum signal at the formation/holding boundary.

    python scripts/run_m4_jt.py

Output: campaign/momentum/m4/us_jt_m4.jsonl
Prints M2 → M4 side-by-side comparison.
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
from aurelius.research.templates import FactorStrategy

STORE_DB = "./data/analytics.duckdb"
US_PRED = "frequency='1d' AND symbol NOT LIKE '%.%'"

# M2 result (institutional baseline for M4 comparison)
M2 = {
    "is_sharpe": 0.3215, "oos_sharpe": 0.098, "oos_return": -0.2379,
    "oos_max_drawdown": -0.7578, "oos_trades": 672, "adjusted_pvalue": 0.4244,
    "verdict": "reject",
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
    out = Path("campaign/momentum/m4/us_jt_m4.jsonl")
    out.parent.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    bars = load_bars()
    ts = sorted({b.timestamp for b in bars})
    syms = sorted({b.symbol for b in bars})
    print(f"[m4] {len(bars)} bars  {len(syms)} securities  "
          f"{ts[0].date()}..{ts[-1].date()}  load {time.time()-t0:.1f}s", flush=True)

    # M4 = M2 (equal_weight + price screen) + skip=21 (JT 1-month skip)
    params = {
        "lookback": 126, "quantile": 0.10, "rebalance_days": 21,
        "allow_short": True, "equal_weight": True, "min_price": 5.0, "skip": 21,
    }
    cfg = research_config(max_position_pct=Decimal("1.0"))

    store = ResearchStore("./data/research_m4_jt.duckdb")
    runner = ResearchRunner(store)
    h = runner.hypothesis(
        statement="JT 6-1-6 decile (US, M4 skip period): a 1-month gap between "
                  "formation and holding removes short-term reversal per JT-1993.",
        rationale="JT-1993 skips the most recent month when ranking so the "
                  "momentum signal is not contaminated by 1-month reversal "
                  "(bid-ask bounce / microstructure). Formation return measured "
                  "lookback+skip..skip bars ago. M1 equal-weight + M2 price screen retained.",
        researcher="m4_methodology_campaign",
    )
    t1 = time.time()
    r = runner.investigate(
        hypothesis=h,
        factory_from_params=lambda p: FactorStrategy(**p),
        base_params=params,
        bars=bars,
        config=cfg,
        param_grid=None,
        features_used=["mom_relative_strength", "price_screen_jt2001",
                       "skip_period_jt1993"],
    )
    rec = {
        "label": "JT_6-1-6_decile_m4",
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

    print(f"\n{'Metric':<22} {'M4 (M2 + skip=21)':>22} {'M2 baseline':>20}")
    print("-" * 66)
    for k, m2_v in [
        ("is_sharpe", M2["is_sharpe"]),
        ("oos_sharpe", M2["oos_sharpe"]),
        ("oos_return", M2["oos_return"]),
        ("oos_max_drawdown", M2["oos_max_drawdown"]),
        ("oos_trades", M2["oos_trades"]),
        ("adjusted_pvalue", M2["adjusted_pvalue"]),
        ("verdict", M2["verdict"]),
    ]:
        m4_v = rec[k]
        print(f"  {k:<20} {m4_v!r:>22}  vs  {m2_v!r:>15}")
    print(f"\nM4 runtime: {rec['runtime_s']:.0f}s  total: {time.time()-t0:.0f}s")
    print(f"Output: {out}")


if __name__ == "__main__":
    main()

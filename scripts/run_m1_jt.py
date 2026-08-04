#!/usr/bin/env python
"""M1 methodology fidelity run — equal-weight within gross leverage budget.

Runs the canonical JT reference config (6-1-6 decile, US) with M1 enabled,
then prints a side-by-side comparison against the published reference.

    python scripts/run_m1_jt.py

Output: campaign/momentum/m1/us_jt_m1.jsonl
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

# Published reference from docs/REPRO_JT_1993_US_REFERENCE.md
REF = {
    "oos_sharpe": 0.935, "oos_return": 0.5878, "oos_max_drawdown": -0.7086,
    "oos_trades": 345, "adjusted_pvalue": 0.161, "verdict": "reject",
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
    out = Path("campaign/momentum/m1/us_jt_m1.jsonl")
    out.parent.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    bars = load_bars()
    ts = sorted({b.timestamp for b in bars})
    syms = sorted({b.symbol for b in bars})
    print(f"[m1] {len(bars)} bars  {len(syms)} securities  "
          f"{ts[0].date()}..{ts[-1].date()}  load {time.time()-t0:.1f}s", flush=True)

    # M1: equal_weight=True + max_position_pct=1.0 so strength IS the NAV fraction
    params = {
        "lookback": 126, "quantile": 0.10, "rebalance_days": 21,
        "allow_short": True, "equal_weight": True,
    }
    cfg = research_config(max_position_pct=Decimal("1.0"))

    store = ResearchStore("./data/research_m1_jt.duckdb")
    runner = ResearchRunner(store)
    h = runner.hypothesis(
        statement="JT 6-1-6 decile (US, M1 equal-weight): equal-weight decile "
                  "expresses fully under the 1.5x gross cap.",
        rationale="M1 replaces fixed 5%/name with budget/n per name → full decile fills.",
        researcher="m1_methodology_campaign",
    )
    t1 = time.time()
    r = runner.investigate(
        hypothesis=h,
        factory_from_params=lambda p: FactorStrategy(**p),
        base_params=params,
        bars=bars,
        config=cfg,
        param_grid=None,
        features_used=["mom_relative_strength"],
    )
    rec = {
        "label": "JT_6-1-6_decile_m1",
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

    print(f"\n{'Metric':<22} {'M1 (equal-weight)':>22} {'Reference (fixed 5%/name)':>26}")
    print("-" * 72)
    for k, ref_v in [
        ("oos_sharpe", REF["oos_sharpe"]),
        ("oos_return", REF["oos_return"]),
        ("oos_max_drawdown", REF["oos_max_drawdown"]),
        ("oos_trades", REF["oos_trades"]),
        ("adjusted_pvalue", REF["adjusted_pvalue"]),
        ("verdict", REF["verdict"]),
    ]:
        m1_v = rec[k]
        fmt = ".3f" if isinstance(m1_v, float) else ""
        print(f"  {k:<20} {m1_v!r:>22}  vs  {ref_v!r:>20}")
    print(f"\nM1 runtime: {rec['runtime_s']:.0f}s  total: {time.time()-t0:.0f}s")
    print(f"Output: {out}")


if __name__ == "__main__":
    main()

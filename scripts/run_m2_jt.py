#!/usr/bin/env python
"""M2 methodology fidelity run — JT universe construction (price screen).

M2 builds on M1 (equal-weight) and adds the JT-2001 price filter: exclude
stocks with price < $5 at formation time. This is the closest implementable
approximation to JT's NYSE/AMEX universe filter given available data.

    python scripts/run_m2_jt.py

Output: campaign/momentum/m2/us_jt_m2.jsonl
Prints M1 → M2 side-by-side comparison.
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
from mentisrex.research.runner import ResearchRunner, research_config
from mentisrex.research.store import ResearchStore
from mentisrex.research.templates import FactorStrategy

STORE_DB = "./data/analytics.duckdb"
US_PRED = "frequency='1d' AND symbol NOT LIKE '%.%'"

# M1 result (baseline for M2 comparison)
M1 = {
    "oos_sharpe": -0.687, "oos_return": -0.6025, "oos_max_drawdown": -1.3083,
    "oos_trades": 848, "adjusted_pvalue": 1.0, "verdict": "reject",
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
    out = Path("campaign/momentum/m2/us_jt_m2.jsonl")
    out.parent.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    bars = load_bars()
    ts = sorted({b.timestamp for b in bars})
    syms = sorted({b.symbol for b in bars})
    print(f"[m2] {len(bars)} bars  {len(syms)} securities  "
          f"{ts[0].date()}..{ts[-1].date()}  load {time.time()-t0:.1f}s", flush=True)

    # M2 = M1 (equal_weight) + min_price=5.0 (JT-2001 price screen)
    params = {
        "lookback": 126, "quantile": 0.10, "rebalance_days": 21,
        "allow_short": True, "equal_weight": True, "min_price": 5.0,
    }
    cfg = research_config(max_position_pct=Decimal("1.0"))

    store = ResearchStore("./data/research_m2_jt.duckdb")
    runner = ResearchRunner(store)
    h = runner.hypothesis(
        statement="JT 6-1-6 decile (US, M2 price screen): exclude price < $5 "
                  "per JT-2001 — removes penny-stock microstructure noise from "
                  "the momentum cross-section.",
        rationale="JT-2001 (same authors) explicitly drops stocks priced below $5. "
                  "75 of 1016 US symbols average below $5. Filter applied at "
                  "formation time per rebalance, not as static universe exclusion.",
        researcher="m2_methodology_campaign",
    )
    t1 = time.time()
    r = runner.investigate(
        hypothesis=h,
        factory_from_params=lambda p: FactorStrategy(**p),
        base_params=params,
        bars=bars,
        config=cfg,
        param_grid=None,
        features_used=["mom_relative_strength", "price_screen_jt2001"],
    )
    rec = {
        "label": "JT_6-1-6_decile_m2",
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

    print(f"\n{'Metric':<22} {'M2 (M1 + price≥$5)':>22} {'M1 baseline':>20}")
    print("-" * 66)
    for k, m1_v in [
        ("oos_sharpe", M1["oos_sharpe"]),
        ("oos_return", M1["oos_return"]),
        ("oos_max_drawdown", M1["oos_max_drawdown"]),
        ("oos_trades", M1["oos_trades"]),
        ("adjusted_pvalue", M1["adjusted_pvalue"]),
        ("verdict", M1["verdict"]),
    ]:
        m2_v = rec[k]
        print(f"  {k:<20} {m2_v!r:>22}  vs  {m1_v!r:>15}")
    print(f"\nM2 runtime: {rec['runtime_s']:.0f}s  total: {time.time()-t0:.0f}s")
    print(f"Output: {out}")


if __name__ == "__main__":
    main()

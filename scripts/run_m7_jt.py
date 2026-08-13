#!/usr/bin/env python
"""M7 liquidity-filter experiment — two runs only, nothing else changes.

  Run A (mode=A): certified baseline (M1+M2+M4), liquidity_filter=False.
  Run B (mode=B): identical baseline + liquidity_filter=True, default metric
                  (median dollar volume), pre-registered liquidity_pct=0.20
                  (bottom quintile dropped), liquidity_window=21.

liquidity_pct=0.20 and liquidity_window=21 are PRE-REGISTERED, single, non-swept
choices (conventional institutional bottom-quintile screen; 21d = 1 month, matching
the rebalance/skip cadence). No sweep, no optimisation.

    python scripts/run_m7_jt.py A campaign/momentum/m7/us_jt_m7_runA.jsonl
    python scripts/run_m7_jt.py B campaign/momentum/m7/us_jt_m7_runB.jsonl
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

BASE = {
    "lookback": 126, "quantile": 0.10, "rebalance_days": 21,
    "allow_short": True, "equal_weight": True, "min_price": 5.0, "skip": 21,
}
FILTER = {"liquidity_filter": True, "liquidity_metric": "dollar_volume_median",
          "liquidity_pct": 0.20, "liquidity_window": 21}


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
    mode = sys.argv[1].upper()
    out = Path(sys.argv[2])
    out.parent.mkdir(parents=True, exist_ok=True)
    assert mode in ("A", "B"), mode

    params = dict(BASE)
    if mode == "B":
        params.update(FILTER)
    label = f"JT_6-1-6_decile_m7_run{mode}"

    t0 = time.time()
    bars = load_bars()
    ts = sorted({b.timestamp for b in bars})
    print(f"[m7-{mode}] {len(bars)} bars  {len({b.symbol for b in bars})} securities  "
          f"{ts[0].date()}..{ts[-1].date()}  load {time.time()-t0:.1f}s", flush=True)

    cfg = research_config(max_position_pct=Decimal("1.0"))
    store = ResearchStore(f"./data/research_m7_run{mode}.duckdb")
    runner = ResearchRunner(store)
    h = runner.hypothesis(
        statement=f"M7 run {mode}: certified JT baseline "
                  f"{'+ median-dollar-volume liquidity screen (bottom 20% dropped)' if mode=='B' else '(liquidity filter OFF)'}.",
        rationale="M6 approved a liquidity screen from close+volume only. Run A is "
                  "the certified baseline; Run B adds the screen, nothing else. "
                  "Pre-registered pct=0.20, window=21, no sweep.",
        researcher="m7_liquidity_campaign",
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
                       "skip_period_jt1993"] + (["liquidity_screen_m7"] if mode == "B" else []),
    )
    rec = {
        "label": label,
        "basis": "net (production)",
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
    print(f"[m7-{mode}] {json.dumps(rec)}", flush=True)
    print(f"[m7-{mode}] total {time.time()-t0:.0f}s -> {out}", flush=True)


if __name__ == "__main__":
    main()

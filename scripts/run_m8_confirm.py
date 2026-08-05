#!/usr/bin/env python
"""M8 end-to-end confirmation — severe universe shrink, baseline vs invariant.

Loads the certified M4 baseline on a severely-shrunk US universe (deterministic
5% subsample → decile of ~3 names, the concentration-explosion regime) and runs it
twice, varying ONLY portfolio construction:

    baseline   : invariant_construction=False  (0.75/_count → 25% single names)
    invariant  : invariant_construction=True    (bounded equal-weight)

Confirms the invariant framework avoids the concentration blow-up end-to-end.
Small universe → runs in seconds (not the full-panel 23 min).

    python scripts/run_m8_confirm.py
Output: campaign/momentum/m8/us_jt_m8_confirm.jsonl (one record per design)
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
FRACTION = 0.05
BASE = {"lookback": 126, "quantile": 0.10, "rebalance_days": 21, "allow_short": True,
        "equal_weight": True, "min_price": 5.0, "skip": 21}


def load_bars(subset: set[str]) -> list[BarData]:
    pred = validated_universe_filter(US_PRED)
    conn = duckdb.connect(STORE_DB, read_only=True)
    cur = conn.execute(
        "SELECT symbol,timestamp,open,high,low,close,volume,frequency "
        f"FROM ohlcv WHERE {pred} ORDER BY timestamp,symbol"
    )
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r, strict=False)) for r in cur.fetchall() if r[0] in subset]
    conn.close()
    return [BarData(symbol=r["symbol"], timestamp=r["timestamp"],
                    open=Decimal(str(r["open"])), high=Decimal(str(r["high"])),
                    low=Decimal(str(r["low"])), close=Decimal(str(r["close"])),
                    volume=Decimal(str(r["volume"])), frequency=r["frequency"])
            for r in rows]


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


def main() -> None:
    out = Path("campaign/momentum/m8/us_jt_m8_confirm.jsonl")
    out.parent.mkdir(parents=True, exist_ok=True)
    subset = universe(FRACTION)
    t0 = time.time()
    bars = load_bars(subset)
    print(f"[m8-confirm] shrink {FRACTION:.0%} → {len({b.symbol for b in bars})} names  "
          f"{len(bars)} bars  load {time.time()-t0:.1f}s", flush=True)
    cfg = research_config(max_position_pct=Decimal("1.0"))

    lines = []
    for design in ("baseline", "invariant"):
        params = dict(BASE, invariant_construction=(design == "invariant"))
        store = ResearchStore(f"./data/research_m8_{design}.duckdb")
        runner = ResearchRunner(store)
        h = runner.hypothesis(
            statement=f"M8 confirm ({design}): certified M4 on a 5%-shrunk US "
                      f"universe, portfolio construction = {design}.",
            rationale="Vary only portfolio construction on a severely shrunk "
                      "universe to confirm the invariant framework bounds "
                      "concentration and avoids the blow-up.",
            researcher="m8_invariance_campaign")
        t1 = time.time()
        r = runner.investigate(hypothesis=h, factory_from_params=lambda p: FactorStrategy(**p),
                               base_params=params, bars=bars, config=cfg, param_grid=None,
                               features_used=["mom_relative_strength", "invariant_construction_m8"])
        rec = {"label": f"JT_6-1-6_decile_m8_{design}", "fraction": FRACTION,
               "params": params, "is_sharpe": round(r.is_sharpe, 4),
               "oos_sharpe": round(r.oos_sharpe, 4), "oos_return": round(r.oos_return, 4),
               "oos_max_drawdown": round(r.oos_max_drawdown, 4), "oos_trades": r.oos_trades,
               "adjusted_pvalue": round(r.adjusted_pvalue, 4), "verdict": r.verdict.value,
               "runtime_s": round(time.time() - t1, 1)}
        store.close()
        lines.append(json.dumps(rec))
        print(f"[m8-{design}] {json.dumps(rec)}", flush=True)
    out.write_text("\n".join(lines) + "\n")
    print(f"[m8-confirm] total {time.time()-t0:.0f}s → {out}", flush=True)


if __name__ == "__main__":
    main()

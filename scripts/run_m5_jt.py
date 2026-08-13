#!/usr/bin/env python
"""M5 reporting-fidelity run — JT-comparable GROSS returns.

Audit finding: the reproduction's reported metrics (return/Sharpe/drawdown) are
NET of all execution costs — commissions (10 bps/side), spread (5 bps/side), and
Almgren-Chriss slippage are folded into fill prices and cash, so the equity curve
is net-of-costs. Jegadeesh & Titman (1993) report GROSS relative-strength returns
(costs are a separate robustness discussion, not deducted from the headline).

To make the reproduction directly comparable to the paper WITHOUT touching the
engine / strategy / portfolio / validation / statistics / risk code, M5 runs the
identical institutional baseline (M1 equal-weight + M2 price screen + M4 skip)
under a ZERO-COST config. Zeroing commission_rate / spread_bps / slippage_impact_bps
are configuration inputs (BacktestConfig), not code changes; the zero-cost equity
path is the GROSS, JT-comparable metric. Net (production) metrics are the already
committed M4 baseline and are preserved unchanged.

    python scripts/run_m5_jt.py

Output: campaign/momentum/m5/us_jt_m5_gross.jsonl
Prints GROSS (M5) vs NET (M4 baseline) side-by-side.

Known limitation: SlippageModel keeps a 5 bps fallback for ZERO-VOLUME bars that
is not wired to slippage_impact_bps (engine-level, frozen). On the real US panel
volume is populated, so residual fallback slippage is negligible; the dominant
cost wedge (commission + spread + variable slippage) is fully removed. Documented
in campaign/momentum/m5/M5_Fidelity_Report.md.
"""
from __future__ import annotations

import json
import logging
import sys
import time
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# Silence per-fill DEBUG logging (I/O-bound); reporting run, not a forensic trace.
logging.disable(logging.INFO)

import duckdb

from mentisrex.backtesting.data.feed import BarData
from mentisrex.market_data.storage.isolation import validated_universe_filter
from mentisrex.research.runner import ResearchRunner, research_config
from mentisrex.research.store import ResearchStore
from mentisrex.research.templates import FactorStrategy

STORE_DB = "./data/analytics.duckdb"
US_PRED = "frequency='1d' AND symbol NOT LIKE '%.%'"

# M4 institutional baseline = NET (production) metrics, already committed.
M4_NET = {
    "is_sharpe": -0.1671, "oos_sharpe": 0.1124, "oos_return": -0.2484,
    "oos_max_drawdown": -0.7724, "oos_trades": 593, "adjusted_pvalue": 0.4134,
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
    out = Path("campaign/momentum/m5/us_jt_m5_gross.jsonl")
    out.parent.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    bars = load_bars()
    ts = sorted({b.timestamp for b in bars})
    syms = sorted({b.symbol for b in bars})
    print(f"[m5] {len(bars)} bars  {len(syms)} securities  "
          f"{ts[0].date()}..{ts[-1].date()}  load {time.time()-t0:.1f}s", flush=True)

    # Same institutional baseline as M4 (M1+M2+M4). Only the COST config differs.
    params = {
        "lookback": 126, "quantile": 0.10, "rebalance_days": 21,
        "allow_short": True, "equal_weight": True, "min_price": 5.0, "skip": 21,
    }
    # GROSS config: zero all cost inputs. Not a code change — config values only.
    cfg = research_config(
        max_position_pct=Decimal("1.0"),
        commission_rate=Decimal("0"),
        spread_bps=Decimal("0"),
        slippage_impact_bps=Decimal("0"),
    )

    store = ResearchStore("./data/research_m5_jt.duckdb")
    runner = ResearchRunner(store)
    h = runner.hypothesis(
        statement="JT 6-1-6 decile (US, M5 GROSS reporting): report gross-of-cost "
                  "returns for direct comparability to JT-1993's headline tables.",
        rationale="JT-1993 reports gross relative-strength returns; Mentisrex reports "
                  "net-of-cost. M5 runs the M4 baseline under a zero-cost config to "
                  "surface the gross-comparable metric; net production metrics (M4) "
                  "are preserved. No engine/strategy/validation/statistics change.",
        researcher="m5_methodology_campaign",
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
                       "skip_period_jt1993", "gross_reporting_jt1993"],
    )
    rec = {
        "label": "JT_6-1-6_decile_m5_gross",
        "basis": "gross (zero commission/spread/slippage)",
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

    print(f"\n{'Metric':<22} {'M5 GROSS':>14} {'M4 NET (baseline)':>20}")
    print("-" * 60)
    for k, net_v in [
        ("is_sharpe", M4_NET["is_sharpe"]),
        ("oos_sharpe", M4_NET["oos_sharpe"]),
        ("oos_return", M4_NET["oos_return"]),
        ("oos_max_drawdown", M4_NET["oos_max_drawdown"]),
        ("oos_trades", M4_NET["oos_trades"]),
        ("adjusted_pvalue", M4_NET["adjusted_pvalue"]),
        ("verdict", M4_NET["verdict"]),
    ]:
        print(f"  {k:<20} {rec[k]!r:>14}  vs  {net_v!r:>15}")
    print(f"\nM5 gross runtime: {rec['runtime_s']:.0f}s  total: {time.time()-t0:.0f}s")
    print(f"Output: {out}")


if __name__ == "__main__":
    main()

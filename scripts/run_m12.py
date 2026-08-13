#!/usr/bin/env python
"""M12 low-volatility runs — one config per invocation.

mode=full  : investigate (IS/OOS + adjusted p, certified framework) AND continuous
             full-sample run_backtest → all metrics. Use for the canonical baseline.
mode=cont  : continuous full-sample run_backtest only (faster) → robustness/deploy.

    python scripts/run_m12.py <label> <mode> <outfile.jsonl>

Corrected-construction standard (M8 invariant) ON for every config. Only pre-registered
single values vary (lookback / rebalance / quantile / estimator / liquidity / cost) —
robustness, NOT optimization. US canonical panel.
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
from mentisrex.research.templates import LowVolStrategy
from mentisrex.research.validation import run_backtest

STORE_DB = "./data/analytics.duckdb"
US_PRED = "frequency='1d' AND symbol NOT LIKE '%.%'"
BASE = dict(lookback=252, quantile=0.10, rebalance_days=21, allow_short=True,
            equal_weight=True, min_price=5.0, invariant_construction=True)
DEFAULT_COST = (10, 5, 10)
CONFIGS = {
    "canonical": (dict(), DEFAULT_COST),
    # Phase 5 robustness (single pre-registered values, no sweep-to-optimize)
    "lb_126": (dict(lookback=126), DEFAULT_COST),
    "lb_504": (dict(lookback=504), DEFAULT_COST),
    "rb_63":  (dict(rebalance_days=63), DEFAULT_COST),
    "q_20":   (dict(quantile=0.20), DEFAULT_COST),
    "downside": (dict(downside=True), DEFAULT_COST),
    # Phase 7 deployability
    "liq_50": (dict(liquidity_filter=True, liquidity_metric="dollar_volume_median",
                    liquidity_pct=0.50, liquidity_window=21), DEFAULT_COST),
    "cost_gross": (dict(), (0, 0, 0)),
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


def sr(x, n=4):
    try:
        return round(x, n)
    except TypeError:
        return round(complex(x).real, n)


def main() -> None:
    label, mode, outfile = sys.argv[1], sys.argv[2], Path(sys.argv[3])
    outfile.parent.mkdir(parents=True, exist_ok=True)
    sp_over, (comm, spread, slip) = CONFIGS[label]
    params = dict(BASE, **sp_over)

    t0 = time.time()
    bars = load_bars()
    cfg = research_config(max_position_pct=Decimal("1.0"),
                          commission_rate=Decimal(comm) / Decimal(10000),
                          spread_bps=Decimal(spread), slippage_impact_bps=Decimal(slip))
    print(f"[m12:{label}] {len(bars)} bars {len({b.symbol for b in bars})} names "
          f"cost {comm}/{spread}/{slip}  load {time.time()-t0:.1f}s", flush=True)

    rec = {"label": label, "mode": mode, "params": params,
           "cost_bps": {"comm": comm, "spread": spread, "slippage": slip}}

    # continuous full-sample metrics (deployment basis)
    m = run_backtest(lambda: LowVolStrategy(**params), bars, cfg)
    rec["continuous"] = {"total_return": sr(m.total_return), "cagr": sr(m.cagr),
        "sharpe": sr(m.sharpe_ratio), "sortino": sr(m.sortino_ratio),
        "max_drawdown": sr(m.max_drawdown), "volatility": sr(m.annualized_volatility),
        "num_trades": m.num_trades, "annual_turnover": sr(m.annual_turnover),
        "avg_holding_days": sr(m.avg_holding_period_days),
        "degenerate": isinstance(m.sortino_ratio, complex) or isinstance(m.annualized_volatility, complex)}

    if mode == "full":
        store = ResearchStore(f"./data/research_m12_{label}.duckdb")
        runner = ResearchRunner(store)
        h = runner.hypothesis(
            statement="M12 low-vol canonical: low-volatility stocks earn superior "
                      "risk-adjusted returns (long low-vol / short high-vol decile).",
            rationale="Baker-Haugen-Baker / Blitz-van Vliet total-volatility anomaly; "
                      "252d stdev of daily returns, decile L/S, monthly, M8 construction.",
            researcher="m12_lowvol_campaign")
        r = runner.investigate(hypothesis=h,
            factory_from_params=lambda p: LowVolStrategy(**p), base_params=params,
            bars=bars, config=cfg, param_grid=None, features_used=["low_volatility_252d"])
        rec["oos"] = {"is_sharpe": sr(r.is_sharpe), "oos_sharpe": sr(r.oos_sharpe),
            "oos_return": sr(r.oos_return), "oos_max_drawdown": sr(r.oos_max_drawdown),
            "oos_trades": r.oos_trades, "adjusted_pvalue": sr(r.adjusted_pvalue),
            "verdict": r.verdict.value}
        store.close()

    rec["runtime_s"] = round(time.time() - t0, 1)
    outfile.write_text(json.dumps(rec) + "\n")
    print(f"[m12:{label}] {json.dumps(rec)}", flush=True)


if __name__ == "__main__":
    main()

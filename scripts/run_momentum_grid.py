#!/usr/bin/env python
"""Momentum campaign driver — cross-sectional momentum, one market, one grid.

Reuses the committed reproduction path VERBATIM (FactorStrategy, ResearchRunner,
research_config, validated_universe_filter). The ONLY things this varies are the
universe (US vs India) and the momentum params, so a robustness/cross-market
grid is the same faithful engine run repeatedly — no tuning, each config judged
once on its own OOS split.

    python scripts/run_momentum_grid.py us      campaign/momentum/runs/us.jsonl
    python scripts/run_momentum_grid.py india   campaign/momentum/runs/india.jsonl

Optional 3rd arg = single config label -> runs ONLY that config, using an
isolated ResearchStore (so N processes can run different configs in parallel
with zero DuckDB write-lock contention; results are identical/deterministic).
Each isolated run writes its own jsonl shard; concat shards after.

    python scripts/run_momentum_grid.py india shards/india_tercile.jsonl tercile

Each grid config -> one JSON line {market,label,params,is_sharpe,oos_sharpe,
oos_return,oos_max_drawdown,oos_trades,adjusted_pvalue,verdict}. Append-only so a
long run is resumable/auditable and a crash keeps completed configs.
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

# India names carry an exchange suffix dot (.NS/.BO); US names have none.
MARKETS = {
    "us": "frequency='1d' AND symbol NOT LIKE '%.%'",
    "india": "frequency='1d' AND symbol LIKE '%.%'",
}

# JT-1993 reference config plus robustness axes: formation (lookback), skip is
# folded into lookback+rebalance cadence, holding = rebalance_days, breadth =
# quantile. Each is ONE run, judged once. Not a tuning grid — a fidelity sweep.
GRID: list[dict] = [
    {"label": "JT_6-1-6_decile", "lookback": 126, "quantile": 0.10, "rebalance_days": 21, "allow_short": True},
    {"label": "form_3m",         "lookback": 63,  "quantile": 0.10, "rebalance_days": 21, "allow_short": True},
    {"label": "form_9m",         "lookback": 189, "quantile": 0.10, "rebalance_days": 21, "allow_short": True},
    {"label": "form_12m",        "lookback": 252, "quantile": 0.10, "rebalance_days": 21, "allow_short": True},
    {"label": "hold_3m",         "lookback": 126, "quantile": 0.10, "rebalance_days": 63, "allow_short": True},
    {"label": "tercile",         "lookback": 126, "quantile": 0.33, "rebalance_days": 21, "allow_short": True},
    {"label": "long_only",       "lookback": 126, "quantile": 0.10, "rebalance_days": 21, "allow_short": False},
]


def load_bars(market: str) -> list[BarData]:
    # read_only so many parallel workers can read the same file concurrently
    # (DuckDB shares read-only locks; the default read-write open is exclusive).
    pred = validated_universe_filter(MARKETS[market])
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
    market = sys.argv[1]
    out = Path(sys.argv[2])
    only_label = sys.argv[3] if len(sys.argv) > 3 else None
    assert market in MARKETS, f"market must be one of {list(MARKETS)}"
    out.parent.mkdir(parents=True, exist_ok=True)
    grid = [c for c in GRID if only_label is None or c["label"] == only_label]
    assert grid, f"no config named {only_label}"
    # Isolated store per parallel worker -> no DuckDB single-writer contention.
    store_path = f"./data/research_{market}_{only_label}.duckdb" if only_label else "./data/research.duckdb"

    done = set()
    if out.exists():
        for line in out.read_text().splitlines():
            if line.strip():
                done.add(json.loads(line)["label"])

    t0 = time.time()
    bars = load_bars(market)
    syms = sorted({b.symbol for b in bars})
    ts = sorted({b.timestamp for b in bars})
    print(f"[{market}] {len(bars)} bars  {len(syms)} securities  "
          f"{ts[0].date()}..{ts[-1].date()}  load {time.time()-t0:.1f}s  "
          f"({len(done)} configs already done)", flush=True)

    store = ResearchStore(store_path)
    runner = ResearchRunner(store)

    with out.open("a") as fh:
        for cfg in grid:
            label = cfg["label"]
            if label in done:
                print(f"[{market}] skip {label} (done)", flush=True)
                continue
            params = {k: v for k, v in cfg.items() if k != "label"}
            h = runner.hypothesis(
                statement=f"Cross-sectional momentum ({label}) — winners beat losers, {market}.",
                rationale="Underreaction -> relative-strength momentum persists 3-12 months (JT 1993).",
                researcher=f"momentum_campaign_{market}",
            )
            t1 = time.time()
            r = runner.investigate(
                hypothesis=h,
                factory_from_params=lambda p: FactorStrategy(**p),
                base_params=params,
                bars=bars,
                config=research_config(),
                param_grid=None,  # single run per config, NO tuning
                features_used=["mom_relative_strength"],
            )
            rec = {
                "market": market, "label": label, "params": params,
                "is_sharpe": round(r.is_sharpe, 4), "oos_sharpe": round(r.oos_sharpe, 4),
                "oos_return": round(r.oos_return, 4), "oos_max_drawdown": round(r.oos_max_drawdown, 4),
                "oos_trades": r.oos_trades, "adjusted_pvalue": round(r.adjusted_pvalue, 4),
                "verdict": r.verdict.value, "runtime_s": round(time.time() - t1, 1),
            }
            fh.write(json.dumps(rec) + "\n")
            fh.flush()
            print(f"[{market}] {label}: OOS Sharpe {r.oos_sharpe:.3f} "
                  f"ret {r.oos_return:.2%} trades {r.oos_trades} "
                  f"{r.verdict.value} ({rec['runtime_s']}s)", flush=True)

    store.close()
    print(f"[{market}] DONE total {time.time()-t0:.1f}s", flush=True)


if __name__ == "__main__":
    main()

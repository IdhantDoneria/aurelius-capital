#!/usr/bin/env python
"""Pairs campaign driver — Gatev distance pairs, one market, one grid.

Reuses the committed path VERBATIM (PairsStrategy composed into MultiPairStrategy,
ResearchRunner, research_config, validated_universe_filter). Selection = Gatev
sum-of-squared-deviation distance over a 12-MONTH formation window (Gatev's own
design; the old toy run used a 6-YEAR formation half, which starved the universe
to ~3 names — the shorter window is MORE faithful, not tuning). Top-N pairs then
trade the whole sample as one diversified book -> one honest IS/OOS portfolio.

    python scripts/run_pairs_grid.py us     campaign/pairs/runs/us.jsonl
    python scripts/run_pairs_grid.py india  campaign/pairs/runs/india.jsonl

Optional 3rd arg = single config label -> runs ONLY that config with an isolated
ResearchStore, so N workers run different configs in parallel with zero DuckDB
write-lock contention (results identical/deterministic). Each writes its own
jsonl shard; concat shards after.

Each config -> one JSON line {market,label,params,is_sharpe,oos_sharpe,
oos_return,oos_max_drawdown,oos_trades,adjusted_pvalue,verdict}. Append-only,
resumable, crash keeps completed configs. NO parameter tuning: each config is
one hypothesis judged once on its own OOS split.
"""
from __future__ import annotations

import json
import statistics
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
from mentisrex.research.templates import MultiPairStrategy

STORE_DB = "./data/analytics.duckdb"

MARKETS = {
    "us": "frequency='1d' AND symbol NOT LIKE '%.%'",
    "india": "frequency='1d' AND symbol LIKE '%.%'",
}

FORMATION_DAYS = 252   # Gatev 12-month formation window
LIQUID_TOP = 300       # cap candidate universe to most-liquid complete-history
                       # names (Gatev screens to liquid CRSP; also bounds SSD O(P^2))

# Robustness/fidelity sweep. Canonical Gatev first, then concentration, entry
# threshold, and spread-window axes. Each is ONE run, judged once. Not tuning.
GRID: list[dict] = [
    {"label": "gatev_top20", "n_pairs": 20, "lookback": 126, "entry_z": 2.0, "exit_z": 0.5},
    {"label": "top5",        "n_pairs": 5,  "lookback": 126, "entry_z": 2.0, "exit_z": 0.5},
    {"label": "top40",       "n_pairs": 40, "lookback": 126, "entry_z": 2.0, "exit_z": 0.5},
    {"label": "entry_1.5",   "n_pairs": 20, "lookback": 126, "entry_z": 1.5, "exit_z": 0.5},
    {"label": "entry_2.5",   "n_pairs": 20, "lookback": 126, "entry_z": 2.5, "exit_z": 0.5},
    {"label": "window_63",   "n_pairs": 20, "lookback": 63,  "entry_z": 2.0, "exit_z": 0.5},
    {"label": "exit_0.25",   "n_pairs": 20, "lookback": 126, "entry_z": 2.0, "exit_z": 0.25},
]


def load_bars(market: str) -> list[BarData]:
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


def select_pairs(bars: list[BarData], n_pairs: int) -> list[tuple]:
    """Gatev distance selection over the first FORMATION_DAYS trading days.

    (1) keep names with COMPLETE history in the formation window (Gatev's aligned
    normalized paths need no gaps); (2) screen to the LIQUID_TOP by formation
    dollar-volume (Gatev uses liquid names; also bounds the O(P^2) SSD); (3)
    normalize each to start=1; (4) rank all pairs by sum-of-squared-deviation,
    return the top n_pairs as (x, y, hedge). hedge scale-balances the raw spread
    the template z-scores, approximating Gatev's normalized-price spread.
    """
    dates = sorted({b.timestamp for b in bars})[:FORMATION_DAYS]
    dset = set(dates)
    px: dict[str, dict] = {}
    dv: dict[str, list] = {}
    for b in bars:
        if b.timestamp in dset:
            px.setdefault(b.symbol, {})[b.timestamp] = float(b.close)
            dv.setdefault(b.symbol, []).append(float(b.close) * float(b.volume))
    complete = [s for s, d in px.items() if len(d) == len(dates)]
    complete.sort(key=lambda s: statistics.median(dv[s]), reverse=True)
    universe = complete[:LIQUID_TOP]

    norm = {s: [px[s][d] / px[s][dates[0]] for d in dates] for s in universe}
    mean_px = {s: statistics.mean(px[s][d] for d in dates) for s in universe}

    ranked: list[tuple] = []
    for i in range(len(universe)):
        a = norm[universe[i]]
        for j in range(i + 1, len(universe)):
            b_ = norm[universe[j]]
            ssd = sum((a[k] - b_[k]) ** 2 for k in range(len(dates)))
            ranked.append((ssd, universe[i], universe[j]))
    ranked.sort(key=lambda t: t[0])

    out = []
    for _, x, y in ranked[:n_pairs]:
        hedge = round(mean_px[x] / mean_px[y], 4) if mean_px[y] else 1.0
        out.append((x, y, hedge))
    return out


def main() -> None:
    market = sys.argv[1]
    out = Path(sys.argv[2])
    only_label = sys.argv[3] if len(sys.argv) > 3 else None
    assert market in MARKETS, f"market must be one of {list(MARKETS)}"
    out.parent.mkdir(parents=True, exist_ok=True)
    grid = [c for c in GRID if only_label is None or c["label"] == only_label]
    assert grid, f"no config named {only_label}"
    store_path = f"./data/research_pairs_{market}_{only_label}.duckdb" if only_label else "./data/research_pairs.duckdb"

    done = set()
    if out.exists():
        for line in out.read_text().splitlines():
            if line.strip():
                done.add(json.loads(line)["label"])

    t0 = time.time()
    bars = load_bars(market)
    ts = sorted({b.timestamp for b in bars})
    print(f"[{market}] {len(bars)} bars  {len({b.symbol for b in bars})} securities  "
          f"{ts[0].date()}..{ts[-1].date()}  load {time.time()-t0:.1f}s  "
          f"({len(done)} done)", flush=True)

    # Pair selection depends only on FORMATION_DAYS (fixed) -> select the max N
    # once, slice per config. Deterministic; SSD ranking is stable.
    max_n = max(c["n_pairs"] for c in grid)
    all_pairs = select_pairs(bars, max_n)
    print(f"[{market}] selected {len(all_pairs)} pairs; top: "
          f"{['/'.join(p[:2]) for p in all_pairs[:3]]}", flush=True)

    store = ResearchStore(store_path)
    runner = ResearchRunner(store)

    with out.open("a") as fh:
        for cfg in grid:
            label = cfg["label"]
            if label in done:
                print(f"[{market}] skip {label} (done)", flush=True)
                continue
            pairs = all_pairs[:cfg["n_pairs"]]
            params = {"pairs": pairs, "lookback": cfg["lookback"],
                      "entry_z": cfg["entry_z"], "exit_z": cfg["exit_z"]}
            h = runner.hypothesis(
                statement=f"Gatev distance pairs ({label}) mean-revert, {market}.",
                rationale="Relative-value spread mean-reversion; min-distance pairs "
                          "co-move, divergences correct (Gatev et al. 2006).",
                researcher=f"pairs_campaign_{market}",
            )
            t1 = time.time()
            r = runner.investigate(
                hypothesis=h,
                factory_from_params=lambda p: MultiPairStrategy(**p),
                base_params=params,
                bars=bars,
                config=research_config(),
                param_grid=None,
                features_used=["pair_spread_zscore"],
            )
            rec = {
                "market": market, "label": label,
                "params": {"n_pairs": cfg["n_pairs"], "lookback": cfg["lookback"],
                           "entry_z": cfg["entry_z"], "exit_z": cfg["exit_z"]},
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

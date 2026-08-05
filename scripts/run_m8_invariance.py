#!/usr/bin/env python
"""M8 controlled invariance experiment — exposure vs universe size.

Exposure (gross/net/max-weight/HHI/constituents) is a deterministic property of the
weight-construction map, so it is measured DIRECTLY on one real momentum
cross-section rather than via a 23-min backtest per shrink level. Build the certified
M4 cross-section on the real US panel at the last rebalance date, then artificially
shrink the universe by controlled fractions (evenly-spaced, momentum-unbiased sample)
and, for each fraction, construct weights two ways:

    baseline   : strength = 0.75/_count           (M4 incumbent)
    invariant  : invariant_weight(_count, ...)     (M8 bounded equal-weight)

and report the exposure table. Nothing but universe size varies.

    python scripts/run_m8_invariance.py
Output: campaign/momentum/m8/invariance_probe.json  (+ printed table)
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import duckdb

from aurelius.market_data.storage.isolation import validated_universe_filter
from aurelius.research.portfolio_construction import (
    baseline_weight, exposures, invariant_weight,
)

STORE_DB = "./data/analytics.duckdb"
US_PRED = "frequency='1d' AND symbol NOT LIKE '%.%'"
LOOKBACK, SKIP, QUANTILE, MIN_PRICE = 126, 21, 0.10, 5.0
BUDGET, W_MAX, N_MIN = 0.75, 0.10, 10  # L/S leg budget + M8 default bounds
FRACTIONS = [1.0, 0.75, 0.50, 0.25, 0.10, 0.05, 0.02]


def formation_scores() -> dict[str, float]:
    """M4 formation return per symbol at the last date: (close[-1-skip] -
    close[-1-skip-lookback]) / close[...], with the $5 screen on current close."""
    conn = duckdb.connect(STORE_DB, read_only=True)
    pred = validated_universe_filter(US_PRED)
    need = LOOKBACK + SKIP + 1
    rows = conn.execute(
        "SELECT symbol, close FROM ("
        "  SELECT symbol, close, timestamp,"
        "         row_number() OVER (PARTITION BY symbol ORDER BY timestamp DESC) rn"
        f"  FROM ohlcv WHERE {pred}) WHERE rn <= {need} ORDER BY symbol, rn DESC"
    ).fetchall()
    conn.close()
    series: dict[str, list[float]] = {}
    for sym, close in rows:
        series.setdefault(sym, []).append(float(close))
    scores: dict[str, float] = {}
    for sym, c in series.items():
        if len(c) < need or c[0] == 0:
            continue
        if float(c[-1]) < MIN_PRICE:  # M2 screen on current close
            continue
        end = c[-1 - SKIP]
        scores[sym] = (end - c[0]) / c[0]
    return scores


def shrink(symbols: list[str], frac: float) -> list[str]:
    """Deterministic, momentum-unbiased subsample: evenly spaced over the sorted
    symbol list (sort order is independent of momentum)."""
    syms = sorted(symbols)
    n = len(syms)
    target = max(3, int(frac * n))
    if target >= n:
        return syms
    idx = [round(i * n / target) for i in range(target)]
    return [syms[min(j, n - 1)] for j in idx]


def build(scores: dict[str, float], design: str) -> dict:
    n = len(scores)
    ranked = sorted(scores.values())
    count = max(1, int(QUANTILE * n))
    lo, hi = ranked[count - 1], ranked[n - count]
    legs: list[tuple[float, int]] = []
    if design == "baseline":
        w = baseline_weight(count, BUDGET)
    else:
        w = invariant_weight(count, BUDGET, W_MAX, N_MIN)
    for v in scores.values():
        if v >= hi:
            legs.append((w, 1))
        elif v <= lo:
            legs.append((w, -1))
    ex = exposures(legs)
    ex["universe_n"] = n
    ex["decile_count"] = count
    ex["design"] = design
    ex["eff_leverage"] = ex["gross"]
    return ex


def main() -> None:
    t0 = time.time()
    out = Path("campaign/momentum/m8/invariance_probe.json")
    out.parent.mkdir(parents=True, exist_ok=True)

    scores = formation_scores()
    syms = list(scores)
    print(f"[m8] full US universe {len(syms)} names  load {time.time()-t0:.1f}s\n")

    records: list[dict] = []
    hdr = (f"{'frac':>5} {'design':>9} {'univ_n':>6} {'decile':>6} "
           f"{'gross':>7} {'net':>9} {'max_w':>8} {'HHI':>9} {'n_names':>7} {'eff_lev':>7}")
    print(hdr)
    print("-" * len(hdr))
    for f in FRACTIONS:
        sub = shrink(syms, f)
        sscores = {s: scores[s] for s in sub}
        for design in ("baseline", "invariant"):
            r = build(sscores, design)
            r["fraction"] = f
            records.append(r)
            print(f"{f:>5.2f} {design:>9} {r['universe_n']:>6} {r['decile_count']:>6} "
                  f"{r['gross']:>7.3f} {r['net']:>9.2e} {r['max_weight']:>8.4f} "
                  f"{r['hhi']:>9.5f} {r['n']:>7} {r['eff_leverage']:>7.3f}")
        print()

    out.write_text(json.dumps(records, indent=2) + "\n")
    # invariance summary: how much does each metric move across shrink levels?
    for design in ("baseline", "invariant"):
        rs = [r for r in records if r["design"] == design]
        mw = [r["max_weight"] for r in rs]
        hhi = [r["hhi"] for r in rs]
        print(f"[{design:>9}] max_weight range {min(mw):.4f}..{max(mw):.4f} "
              f"(x{max(mw)/min(mw):.1f})   HHI range {min(hhi):.5f}..{max(hhi):.5f} "
              f"(x{max(hhi)/min(hhi):.1f})")
    print(f"\nSector concentration: n/a — no sector/industry metadata (per M6).")
    print(f"Output: {out}   total {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()

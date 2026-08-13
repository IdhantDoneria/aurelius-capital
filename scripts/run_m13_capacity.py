#!/usr/bin/env python
"""M13 Phase 4 — long-only low-vol capacity (analytic, India ₹).

Long-only: capacity is bound by the least-liquid name in the LOW-vol (long) decile
only — no short leg. Budget is the full 1.0 book (vs 0.75 in the M12 L/S run), so
per-name weight is larger and the ceiling is correspondingly lower.

Rank India (.NS) names by trailing 252d stdev of daily returns; take the low-vol
decile. Per-name weight = M8 invariant weight at budget 1.0. Ceiling = largest ₹
size keeping the p10 (least-liquid) name ≤10% of 21d median ₹-volume.

    python scripts/run_m13_capacity.py
Output: campaign/lowvol_longonly/capacity_india.json
"""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import duckdb

from mentisrex.market_data.storage.isolation import validated_universe_filter
from mentisrex.research.portfolio_construction import invariant_weight

STORE_DB = "./data/analytics.duckdb"
IN_PRED = "frequency='1d' AND symbol LIKE '%.NS'"
LOOKBACK, QUANTILE, MIN_PRICE, LIQ_WIN = 252, 0.10, 5.0, 21
BUDGET, W_MAX, N_MIN, CAP = 1.0, 0.10, 10, 0.10  # long-only: full 1.0 budget
SIZES = [("₹10L", 10e5), ("₹50L", 50e5), ("₹1cr", 1e7), ("₹5cr", 5e7),
         ("₹10cr", 10e7), ("₹50cr", 50e7), ("₹100cr", 100e7)]


def load() -> dict[str, tuple[float, float]]:
    conn = duckdb.connect(STORE_DB, read_only=True)
    pred = validated_universe_filter(IN_PRED)
    need = LOOKBACK + 1
    rows = conn.execute(
        "SELECT symbol, close, volume FROM ("
        "  SELECT symbol, close, volume, timestamp,"
        "         row_number() OVER (PARTITION BY symbol ORDER BY timestamp DESC) rn"
        f"  FROM ohlcv WHERE {pred}) WHERE rn <= {need} ORDER BY symbol, rn DESC"
    ).fetchall()
    conn.close()
    by: dict[str, list[tuple[float, float]]] = {}
    for sym, close, vol in rows:
        by.setdefault(sym, []).append((float(close), float(vol)))
    out = {}
    for sym, cv in by.items():
        if len(cv) < need or cv[-1][0] < MIN_PRICE:
            continue
        closes = [c for c, _ in cv]
        rets = [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes)) if closes[i - 1]]
        if len(rets) < 2:
            continue
        vol = statistics.pstdev(rets)
        advs = [c * v for c, v in cv[-LIQ_WIN:]]
        out[sym] = (vol, statistics.median(advs))
    return out


def leg_report(name: str, advs: list[float], weight: float) -> dict:
    advs = sorted(advs)
    adv_med = statistics.median(advs)
    adv_p10 = advs[max(0, int(0.10 * len(advs)) - 1)]
    curve = []
    for sz_name, size in SIZES:
        pos = size * weight
        curve.append({"size": sz_name, "adv_pct_median": round(pos / adv_med, 4),
                      "adv_pct_p10": round(pos / adv_p10, 4)})
    ceil_med = CAP * adv_med / weight
    ceil_p10 = CAP * adv_p10 / weight
    print(f"  [{name}] adv_median ₹{adv_med/1e7:.2f}cr  p10 ₹{adv_p10/1e7:.3f}cr  "
          f"ceiling median ₹{ceil_med/1e7:.1f}cr  p10 ₹{ceil_p10/1e7:.2f}cr")
    return {"adv_median_inr": adv_med, "adv_p10_inr": adv_p10,
            "ceiling_median_inr": ceil_med, "ceiling_p10_inr": ceil_p10, "curve": curve}


def main() -> None:
    out = Path("campaign/lowvol_longonly/capacity_india.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    data = load()
    n = len(data)
    decile = max(1, int(QUANTILE * n))
    weight = invariant_weight(decile, BUDGET, W_MAX, N_MIN)
    ranked = sorted(data.items(), key=lambda kv: kv[1][0])  # by vol ascending
    low = ranked[:decile]        # low-vol decile (long) — the only held leg
    print(f"[capacity] India {n} names  decile {decile}  weight {weight:.4f}  budget {BUDGET}")
    low_r = leg_report("low-vol (long)", [adv for _, (_, adv) in low], weight)
    out.write_text(json.dumps({"universe_n": n, "decile_count": decile,
        "per_name_weight": weight, "participation_cap": CAP, "budget": BUDGET,
        "low_vol_long": low_r}, indent=2) + "\n")
    print(f"Output: {out}")


if __name__ == "__main__":
    main()

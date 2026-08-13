#!/usr/bin/env python
"""M10 Phase 3 — capacity scaling (analytic, India ₹).

No backtest: capacity is a footprint calculation. For the India (.NS) eligible
universe, take each name's 21-day median daily ₹-volume (close×volume) at the last
date. The corrected strategy holds an equal-weight decile L/S book: per-name target
weight = min(0.75/decile_count, M8 cap 0.10). For each portfolio size, position
notional = size × weight, and ADV% = position ÷ name's median daily ₹-volume.

Report, per portfolio size: per-name position, ADV% at the MEDIAN-liquidity and
10th-percentile (least-liquid) held name, execution-difficulty tier, and the
capacity ceiling = largest size keeping participation ≤10% ADV.

    python scripts/run_m10_capacity.py
Output: campaign/momentum/m10/capacity_india.json (+ printed curve)
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
LOOKBACK, SKIP, QUANTILE, MIN_PRICE, LIQ_WIN = 126, 21, 0.10, 5.0, 21
BUDGET, W_MAX, N_MIN = 0.75, 0.10, 10
# ₹ sizes: 10 lakh .. 100 crore  (1 lakh=1e5, 1 crore=1e7)
SIZES = [("₹10L", 10e5), ("₹50L", 50e5), ("₹1cr", 1e7), ("₹5cr", 5e7),
         ("₹10cr", 10e7), ("₹50cr", 50e7), ("₹100cr", 100e7)]
PARTICIPATION_CAP = 0.10  # ceiling defined at 10% ADV


def median_dollar_volumes() -> list[float]:
    """21-day median daily ₹-volume for each eligible India name (min_price screen,
    full formation history)."""
    conn = duckdb.connect(STORE_DB, read_only=True)
    pred = validated_universe_filter(IN_PRED)
    need = LOOKBACK + SKIP + 1
    rows = conn.execute(
        "SELECT symbol, close, volume FROM ("
        "  SELECT symbol, close, volume, timestamp,"
        "         row_number() OVER (PARTITION BY symbol ORDER BY timestamp DESC) rn"
        f"  FROM ohlcv WHERE {pred}) WHERE rn <= {need} ORDER BY symbol, rn"
    ).fetchall()
    conn.close()
    by: dict[str, list[tuple[float, float]]] = {}
    for sym, close, vol in rows:
        by.setdefault(sym, []).append((float(close), float(vol)))
    advs = []
    for sym, cv in by.items():
        if len(cv) < need or cv[0][0] < MIN_PRICE:  # rn=1 is latest close
            continue
        recent = cv[:LIQ_WIN]  # most recent 21 days
        advs.append(statistics.median(c * v for c, v in recent))
    return advs


def tier(pct: float) -> str:
    if pct <= 0.01:
        return "easy"
    if pct <= 0.10:
        return "moderate"
    if pct <= 0.50:
        return "hard"
    return "infeasible"


def main() -> None:
    out = Path("campaign/momentum/m10/capacity_india.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    advs = sorted(median_dollar_volumes())
    n = len(advs)
    decile = max(1, int(QUANTILE * n))
    weight = invariant_weight(decile, BUDGET, W_MAX, N_MIN)
    adv_median = statistics.median(advs)
    adv_p10 = advs[max(0, int(0.10 * n) - 1)]  # 10th-percentile (least liquid) name

    print(f"[capacity] India eligible names {n}  decile {decile}  "
          f"per-name weight {weight:.4f}")
    print(f"[capacity] median daily ₹-vol ₹{adv_median/1e7:.2f}cr  "
          f"p10 ₹{adv_p10/1e7:.3f}cr\n")

    hdr = f"{'size':>8} {'position':>12} {'ADV%(median)':>13} {'ADV%(p10)':>11} {'tier(p10)':>11}"
    print(hdr); print("-" * len(hdr))
    records = []
    for name, size in SIZES:
        pos = size * weight
        advp_med = pos / adv_median
        advp_p10 = pos / adv_p10
        r = {"size": name, "size_inr": size, "per_name_position_inr": round(pos),
             "adv_pct_median": round(advp_med, 4), "adv_pct_p10": round(advp_p10, 4),
             "tier_median": tier(advp_med), "tier_p10": tier(advp_p10)}
        records.append(r)
        print(f"{name:>8} ₹{pos/1e7:>9.3f}cr {advp_med:>12.2%} {advp_p10:>10.2%} {tier(advp_p10):>11}")

    # capacity ceiling: largest size keeping the median / p10 name <= 10% ADV
    ceil_med = PARTICIPATION_CAP * adv_median / weight
    ceil_p10 = PARTICIPATION_CAP * adv_p10 / weight
    print(f"\nCapacity ceiling (median name ≤10% ADV): ₹{ceil_med/1e7:.1f}cr")
    print(f"Capacity ceiling (p10 least-liquid name ≤10% ADV): ₹{ceil_p10/1e7:.2f}cr")
    out.write_text(json.dumps({
        "universe_n": n, "decile_count": decile, "per_name_weight": weight,
        "adv_median_inr": adv_median, "adv_p10_inr": adv_p10,
        "participation_cap": PARTICIPATION_CAP,
        "ceiling_median_inr": ceil_med, "ceiling_p10_inr": ceil_p10,
        "curve": records}, indent=2) + "\n")
    print(f"Output: {out}")


if __name__ == "__main__":
    main()

"""M8 portfolio-construction invariance framework.

Problem (M7 root cause, verified): the equal-weight strength is `budget/_count`
where `_count = int(quantile · n)` grows/shrinks with the investable universe `n`.
So when a universe-reducing methodology (liquidity, market-cap, exchange, or
survivorship filter) shrinks `n`, `_count` shrinks and per-name weight `budget/_count`
**rises without bound**: single-name weight and HHI concentration explode, which
under the frozen 1.5× leverage cap drives the catastrophic drawdowns seen in M7.

Gross leg budget is already invariant (a synchronous leg of `_count` names each at
`budget/_count` sums to `budget`). What is NOT invariant is single-name
concentration (max weight, HHI) — and that is the portfolio-construction-controllable
channel M8 targets. Net/gross *drift* in a live backtest also has async-vintage +
leverage-cap drivers that are engine-level (frozen, out of M8 scope).

RECOMMENDED INVARIANT DESIGN — bounded equal-weight (the union of the invariance-
relevant candidates: constant-gross normalization + single-name cap + minimum-
constituent floor):

    weight = min( budget / max(count, n_min), w_max )

  * constant gross: each leg still targets `budget` while the cap is slack.
  * single-name cap `w_max`: max weight can never exceed w_max, so HHI is bounded
    regardless of how small the universe gets — no concentration explosion.
  * minimum-constituent floor `n_min`: below n_min names the leg de-levers
    (denominator floored at n_min) instead of concentrating into a few names.

Baseline-preserving: at the full universe `_count` (~100 per leg here) is >> n_min
and `budget/_count` (~0.0075) << w_max, so both bounds are slack and the weight is
byte-identical to the M4 baseline `budget/_count`. Deterministic, no look-ahead
(depends only on counts known at rebalance t).

Volatility scaling / risk budgeting were investigated and rejected for the standard:
they need a covariance estimate (extra state, look-ahead risk) and do not address the
concentration channel the cap fixes directly. Dollar-neutral per-leg normalization is
subsumed — with the cap slack, both legs target `budget`, so net ≈ 0 by construction.
"""

from __future__ import annotations


def baseline_weight(count: int, budget: float) -> float:
    """Incumbent M4 construction: equal share of the leg budget. Per-name weight
    rises without bound as the universe (hence `count`) shrinks."""
    return budget / count


def invariant_weight(count: int, budget: float, w_max: float, n_min: int) -> float:
    """Bounded equal-weight: constant-gross + single-name cap + min-constituent
    floor. Equals baseline_weight when both bounds are slack (full universe)."""
    return min(budget / max(count, n_min), w_max)


def exposures(weights: list[tuple[float, int]]) -> dict:
    """Portfolio exposure snapshot from (signed_weight, sign) legs.

    `weights`: list of (per_name_weight, direction) where direction is +1 long,
    -1 short, and per_name_weight >= 0. Returns gross, net, max single-name weight,
    HHI (sum of squared weights, scale-free concentration), and constituent count."""
    if not weights:
        return {"gross": 0.0, "net": 0.0, "max_weight": 0.0, "hhi": 0.0, "n": 0}
    gross = sum(w for w, _ in weights)
    net = sum(w * s for w, s in weights)
    max_w = max(w for w, _ in weights)
    hhi = sum(w * w for w, _ in weights)
    return {"gross": gross, "net": net, "max_weight": max_w, "hhi": hhi,
            "n": len(weights)}


if __name__ == "__main__":
    B, WMAX, NMIN = 0.75, 0.10, 10
    # full universe: bounds slack -> invariant == baseline (byte-identical)
    assert invariant_weight(100, B, WMAX, NMIN) == baseline_weight(100, B)
    # moderate shrink: still slack
    assert invariant_weight(20, B, WMAX, NMIN) == baseline_weight(20, B)
    # severe shrink: baseline concentrates to 15% single name
    assert baseline_weight(5, B) == 0.15
    # invariant floors the denominator at n_min -> de-levered, bounded weight
    assert invariant_weight(5, B, WMAX, NMIN) == B / NMIN     # 0.075 (floor binds)
    assert invariant_weight(3, B, WMAX, NMIN) == B / NMIN     # same floor
    # the single-name cap binds independently when n_min is small
    assert invariant_weight(5, 1.0, 0.05, 1) == 0.05          # cap binds, not floor
    # both bounds keep invariant weight <= baseline under shrink
    assert invariant_weight(5, B, WMAX, NMIN) < baseline_weight(5, B)
    # exposure snapshot: symmetric L/S -> net 0, gross = 2*count*w
    legs = [(0.0075, 1)] * 100 + [(0.0075, -1)] * 100
    ex = exposures(legs)
    assert abs(ex["net"]) < 1e-12 and abs(ex["gross"] - 1.5) < 1e-9
    print("portfolio_construction self-check OK")

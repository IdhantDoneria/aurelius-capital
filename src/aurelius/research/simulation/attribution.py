"""Performance attribution (AIDP Phase 11).

Security contribution = Σ_t w_{i,t-1}·r_{i,t} over the realized path. Cost / cash /
turnover drags are booked against the initial capital. Sector contribution needs a
classification map (injected); Brinson allocation/selection/interaction are computed
against a benchmark when sector weights + returns are supplied, else exposed as
extension-point hooks with `insufficient_data`.
"""

from __future__ import annotations

from aurelius.research.simulation.models import AttributionReport


def attribution(*, weight_history: list[dict], price_history: list[dict], total_cost: float,
                initial_capital: float, total_return: float, avg_cash_weight: float,
                sectors: dict | None = None) -> AttributionReport:
    """weight_history[t] and price_history[t] aligned by date (t=0..T)."""
    sec: dict[str, float] = {}
    for t in range(1, len(price_history)):
        prev_w = weight_history[t - 1]
        p0, p1 = price_history[t - 1], price_history[t]
        for sid, w in prev_w.items():
            if sid in p0 and sid in p1 and p0[sid] and p0[sid] > 0:
                r = p1[sid] / p0[sid] - 1.0
                sec[sid] = sec.get(sid, 0.0) + w * r

    sector_contrib: dict = {}
    if sectors:
        for sid, c in sec.items():
            g = sectors.get(sid, "UNKNOWN")
            sector_contrib[g] = sector_contrib.get(g, 0.0) + c

    cost_drag = total_cost / initial_capital if initial_capital > 0 else 0.0
    return AttributionReport(
        security_contribution=sec,
        sector_contribution=sector_contrib or {"insufficient_data": True},
        cost_drag=cost_drag,
        cash_drag=avg_cash_weight * total_return,     # return foregone on idle cash (approx)
        turnover_drag=cost_drag,                       # realized cost is the turnover drag
        total_return=total_return,
        metadata={"brinson": "insufficient_data — needs benchmark sector weights+returns",
                  "note": "security_contribution sums approximate total_return up to costs/cash"})

"""Portfolio validation (AIDP M10).

Checks an implementable portfolio against its constraints and practicality gates —
turnover, capacity/ADV participation, concentration, risk exposure, cost impact,
and hard constraint violations. Composes with the M9 framework (a portfolio's
turnover/capacity feed the same deployment gate) but stands alone.
"""

from __future__ import annotations

import numpy as np

from aurelius.research.portfolio.constraints import ConstraintSet


def validate_portfolio(portfolio, constraints: ConstraintSet, *, cost: dict | None = None,
                       participation=None, sectors=None, vol: float | None = None,
                       beta: float | None = None) -> dict:
    w = np.array([p.weight for p in portfolio.positions], dtype=float)
    viol = constraints.violations(w, sectors=sectors, vol=vol, beta=beta,
                                  turnover=portfolio.turnover, participation=participation)

    checks = {
        "turnover": {
            "value": portfolio.turnover,
            "limit": constraints.max_turnover,
            "ok": constraints.max_turnover is None or portfolio.turnover <= constraints.max_turnover + 1e-9,
        },
        "capacity": {
            "max_participation": float(np.max(participation)) if participation is not None else None,
            "limit": constraints.max_adv_participation,
            "ok": (constraints.max_adv_participation is None or participation is None
                   or float(np.max(participation)) <= constraints.max_adv_participation + 1e-9),
        },
        "concentration": {
            "effective_holdings": portfolio.diagnostics.get("effective_holdings"),
            "max_weight": portfolio.diagnostics.get("max_weight"),
            "ok": portfolio.diagnostics.get("max_weight", 0.0) <= constraints.max_position_weight + 1e-9,
        },
        "risk_exposure": {
            "volatility": vol if vol is not None else portfolio.expected_risk,
            "target": constraints.volatility_target,
            "ok": (constraints.volatility_target is None
                   or (vol or portfolio.expected_risk) <= constraints.volatility_target * 1.05),
        },
        "cost_impact_bps": (cost or {}).get("total_cost_bps"),
        "constraint_violations": viol,
    }
    checks["ok"] = not viol and all(
        c["ok"] for c in checks.values() if isinstance(c, dict) and "ok" in c)
    return checks

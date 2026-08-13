"""Report assembly (AIDP M11). Builds the cost / turnover / capacity reports
from the recorded trades, rebalance events, and exposures."""

from __future__ import annotations

import numpy as np

from mentisrex.research.simulation.models import (
    CapacityReport,
    CostReport,
    TurnoverReport,
)


def cost_report(trades, *, initial_capital: float, n_years: float) -> CostReport:
    if not trades:
        return CostReport(0, 0, 0, 0, 0)
    total = sum(t.cost for t in trades)
    traded = sum(abs(t.notional) for t in trades) or 1.0
    return CostReport(
        total_cost=total, linear_cost=total, impact_cost=0.0,
        cost_bps_of_traded=total / traded * 1e4,
        cost_drag_annualized=total / initial_capital / max(n_years, 1e-9))


def turnover_report(trades, avg_value: float, *, n_years: float, n_trades: int,
                    avg_holding_days: float) -> TurnoverReport:
    two_way = sum(abs(t.notional) for t in trades)
    one_way = two_way / 2.0
    ann = one_way / max(avg_value, 1e-9) / max(n_years, 1e-9)
    return TurnoverReport(annualized_turnover=ann, total_two_way_turnover=two_way,
                          avg_holding_days=avg_holding_days, n_trades=n_trades)


def capacity_report(trades, adv_provider) -> CapacityReport:
    if not trades or adv_provider is None:
        return CapacityReport(0.0, 0.0, "unknown" if adv_provider is None else "no_trades")
    parts = []
    for t in trades:
        adv = adv_provider(t.security_id, t.date)
        if adv and adv > 0:
            parts.append(abs(t.notional) / adv)
    if not parts:
        return CapacityReport(0.0, 0.0, "no_adv")
    p = np.array(parts)
    signal = "high" if p.mean() > 0.1 else ("moderate" if p.mean() > 0.02 else "low")
    return CapacityReport(float(p.mean()), float(p.max()), signal)

"""Execution cost attribution (AIDP M14).

Reuses the M10 `TransactionCostModel` (commission + half-spread + slippage + √-law
impact) — the estimator is NOT re-implemented; this module *attributes* realised and
modelled costs into components and computes implementation shortfall against the
order's arrival price.

Two notions of cost, kept distinct:
  * explicit/modelled cost  — from the M10 model (what a cost model predicts).
  * arrival slippage / IS   — realised (avg fill − arrival)·qty, the market's verdict.
"""

from __future__ import annotations

from aurelius.research.execution.ems.models import CostAnalysis
from aurelius.research.portfolio.costs import TransactionCostModel

DEFAULT_COST_MODEL = TransactionCostModel()


def attribute(report, *, cost_model: TransactionCostModel | None = None,
              adv: float | None = None) -> CostAnalysis:
    """Break a filled order's cost into components + shortfall. `report` is an
    `ExecutionReport`; `report.total_cost` is the realised broker cost."""
    cm = cost_model or DEFAULT_COST_MODEL
    filled = report.filled_quantity
    notional = abs(filled * report.avg_fill_price)

    # component split from the M10 model's bps weights on the traded notional
    est = cm.estimate([notional], adv=[adv] if adv is not None else None)
    impact = est["impact_cost"]
    commission = cm.commission_bps / 1e4 * notional
    spread = (cm.spread_bps / 2.0) / 1e4 * notional
    slippage = cm.slippage_bps / 1e4 * notional

    arrival = report.arrival_price
    # realised arrival slippage: signed adverse move on filled shares, in $ and bps
    is_dollars = (report.avg_fill_price - arrival) * filled if arrival else 0.0
    arr_slip_bps = _bps(is_dollars, notional)
    # implementation shortfall includes explicit realised cost on top of price drift
    is_total_bps = _bps(is_dollars + report.total_cost, notional)

    return CostAnalysis(
        order_id=report.order_id,
        commission=commission, spread=spread, slippage=slippage, impact=impact,
        total_cost=report.total_cost,
        total_cost_bps=_bps(report.total_cost, notional),
        implementation_shortfall_bps=is_total_bps,
        arrival_slippage_bps=arr_slip_bps)


def _bps(amount: float, notional: float) -> float:
    return (amount / notional * 1e4) if notional > 0 else 0.0

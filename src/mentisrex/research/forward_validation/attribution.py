"""Attribution adapter for forward validation (M24).

Thin adapter over M11 simulation.attribution. Allows M24 to compute
forward P&L attribution without duplicating the M11 engine.
"""

from __future__ import annotations


def forward_attribution(
    weight_history: list[dict],
    price_history: list[dict],
    total_cost: float,
    initial_capital: float,
    total_return: float,
    avg_cash_weight: float,
    sectors: dict | None = None,
) -> dict:
    """Compute forward P&L attribution reusing M11 attribution engine.

    weight_history: list of {sid: weight} dicts aligned by date with price_history
    price_history:  list of {sid: price} dicts aligned by date

    Returns a dict derived from M11 AttributionReport.
    If weight_history or price_history is insufficient, returns a stub.
    """
    if len(weight_history) < 2 or len(price_history) < 2:
        return {
            "analyzed": False,
            "reason": "insufficient weight/price history for attribution",
            "note": "attribution requires at least 2 aligned weight+price observations",
        }

    # ponytail: delegate entirely to M11 — no second P&L engine
    from mentisrex.research.simulation.attribution import attribution

    try:
        report = attribution(
            weight_history=weight_history,
            price_history=price_history,
            total_cost=total_cost,
            initial_capital=initial_capital,
            total_return=total_return,
            avg_cash_weight=avg_cash_weight,
            sectors=sectors,
        )
        return {
            "analyzed": True,
            "security_contribution": report.security_contribution,
            "sector_contribution": report.sector_contribution,
            "cost_drag": report.cost_drag,
            "cash_drag": report.cash_drag,
            "turnover_drag": report.turnover_drag,
            "total_return": report.total_return,
            "metadata": report.metadata,
        }
    except Exception as exc:
        return {
            "analyzed": False,
            "reason": f"attribution failed: {exc}",
            "note": "forward attribution requires aligned weight/price history from M23",
        }

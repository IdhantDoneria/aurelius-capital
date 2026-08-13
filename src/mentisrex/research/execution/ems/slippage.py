"""Slippage measurement (AIDP M14).

Arrival-price slippage per order and aggregated across a session. Convention:
positive bps = adverse (a buy filled above arrival, a sell filled below). Signed by
side so longs and shorts aggregate correctly. Pure arithmetic on fills — no model.
"""

from __future__ import annotations


def arrival_slippage_bps(avg_fill_price: float, arrival_price: float, quantity: float) -> float:
    """Adverse move vs arrival, in bps, signed so >0 always means worse execution."""
    if arrival_price <= 0 or quantity == 0:
        return 0.0
    raw = (avg_fill_price - arrival_price) / arrival_price * 1e4
    return raw if quantity > 0 else -raw          # sells: filling low is adverse


def report_slippage(report) -> float:
    return arrival_slippage_bps(report.avg_fill_price, report.arrival_price, report.filled_quantity)


def aggregate_slippage_bps(reports) -> float:
    """Notional-weighted mean arrival slippage across filled orders."""
    num = den = 0.0
    for r in reports:
        notional = abs(r.filled_quantity * r.avg_fill_price)
        num += report_slippage(r) * notional
        den += notional
    return num / den if den > 0 else 0.0

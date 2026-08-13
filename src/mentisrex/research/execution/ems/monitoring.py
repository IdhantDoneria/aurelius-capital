"""Execution monitoring & post-trade analytics (AIDP M14).

Aggregates a session into `ExecutionMetrics` (fill quality, cost, slippage,
implementation shortfall) and raises alerts (duplicate fills, unfilled/blocked
orders, over-fills). Also groups performance by algorithm and by broker — the
post-trade attribution the milestone asks for. Pure reads over the session.
"""

from __future__ import annotations

from mentisrex.research.execution.ems.models import ExecutionMetrics, OrderStatus
from mentisrex.research.execution.ems.slippage import aggregate_slippage_bps


def metrics(session) -> ExecutionMetrics:
    reports = session.reports()
    filled = [r for r in reports if abs(r.filled_quantity) > 0]

    req_notional = sum(abs(r.requested_quantity * r.arrival_price) for r in reports)
    fill_notional = sum(abs(r.filled_quantity * r.avg_fill_price) for r in filled)
    total_cost = sum(r.total_cost for r in reports)
    req_shares = sum(abs(r.requested_quantity) for r in reports) or 1.0
    fill_shares = sum(abs(r.filled_quantity) for r in reports)

    is_num = sum(r.implementation_shortfall_bps * abs(r.filled_quantity * r.avg_fill_price) for r in filled)

    return ExecutionMetrics(
        n_orders=len(reports),
        n_filled=sum(r.status == OrderStatus.FILLED for r in reports),
        n_partial=sum(r.status == OrderStatus.PARTIALLY_FILLED for r in reports),
        n_rejected=sum(r.status == OrderStatus.REJECTED for r in reports),
        n_cancelled=sum(r.status == OrderStatus.CANCELLED for r in reports),
        n_child_orders=sum(len(p.child_orders) for p in session.plans),
        n_fills=len(session.fills),
        fill_rate=fill_shares / req_shares,
        total_requested_notional=req_notional,
        total_filled_notional=fill_notional,
        total_cost=total_cost,
        total_cost_bps=(total_cost / fill_notional * 1e4) if fill_notional > 0 else 0.0,
        avg_slippage_bps=aggregate_slippage_bps(filled),
        avg_implementation_shortfall_bps=(is_num / fill_notional) if fill_notional > 0 else 0.0,
        alerts=_alerts(session, reports))


def by_algorithm(session) -> dict:
    """Per-algorithm fill rate / cost bps / slippage bps."""
    groups: dict = {}
    reports = {r.order_id: r for r in session.reports()}
    for d in session.routing_decisions:
        groups.setdefault(d.algo, []).append(reports[d.order_id])
    return {algo: _group_stats(rs) for algo, rs in groups.items()}


def by_broker(session) -> dict:
    groups: dict = {}
    reports = {r.order_id: r for r in session.reports()}
    for d in session.routing_decisions:
        groups.setdefault(d.broker, []).append(reports[d.order_id])
    return {broker: _group_stats(rs) for broker, rs in groups.items()}


def _group_stats(reports) -> dict:
    filled = [r for r in reports if abs(r.filled_quantity) > 0]
    fill_notional = sum(abs(r.filled_quantity * r.avg_fill_price) for r in filled)
    cost = sum(r.total_cost for r in reports)
    req_shares = sum(abs(r.requested_quantity) for r in reports) or 1.0
    return {
        "n_orders": len(reports),
        "fill_rate": sum(abs(r.filled_quantity) for r in reports) / req_shares,
        "total_cost": cost,
        "cost_bps": (cost / fill_notional * 1e4) if fill_notional > 0 else 0.0,
        "avg_slippage_bps": aggregate_slippage_bps(filled),
    }


def _alerts(session, reports) -> list:
    out = []
    if session.fills_processor.n_duplicates:
        out.append(f"duplicate_fills:{session.fills_processor.n_duplicates}")
    n_blocked = sum(r.status == OrderStatus.REJECTED for r in reports)
    if n_blocked:
        out.append(f"rejected_orders:{n_blocked}")
    for r in reports:
        if abs(r.filled_quantity) - abs(r.requested_quantity) > 1e-6:
            out.append(f"over_fill:{r.order_id}")
    return out

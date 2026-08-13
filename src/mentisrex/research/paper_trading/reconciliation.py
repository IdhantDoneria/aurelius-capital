"""Reconciliation engine (AIDP M12).

Compares the internal book (reused M11 `PortfolioState`) against the external
`BrokerAccount` and emits every discrepancy as a `StateDifference`. Detects the
nine institutional break categories:

  missing_position, unexpected_position, wrong_quantity, wrong_price,
  cash_mismatch, stale_order, duplicate_fill, missing_fill, wrong_cost_basis

Pure comparison — no state mutation, deterministic ordering.
"""

from __future__ import annotations

from dataclasses import dataclass

from mentisrex.research.paper_trading.models import ReconciliationReport, StateDifference


@dataclass(frozen=True)
class ReconciliationConfig:
    qty_tol: float = 1e-6
    cash_tol_frac: float = 1e-4           # of total value
    price_tol_bps: float = 1.0
    cost_basis_tol_bps: float = 10.0
    stale_order_days: int = 5


def reconcile(internal, external, *, when=None, config: ReconciliationConfig | None = None,
              pending_orders=None, applied_fill_ids=None, broker_fill_ids=None,
              as_of_seq=None) -> ReconciliationReport:
    """`internal`: M11 PortfolioState. `external`: BrokerAccount.
    `pending_orders`: list of (client_order_id, age_days) still open → stale check.
    `applied_fill_ids` / `broker_fill_ids`: for duplicate/missing-fill detection."""
    cfg = config or ReconciliationConfig()
    diffs: list[StateDifference] = []
    value = max(external.total_value(), internal.total_value(), 1.0)

    ih = internal.holdings
    ep = external.positions
    sids = set(ih) | set(ep)
    for sid in sorted(sids):
        h = ih.get(sid)
        e = ep.get(sid)
        iq = h.shares if h else 0.0
        eq = e.quantity if e else 0.0
        if h and not e:
            diffs.append(StateDifference(sid, "missing_position", iq, 0.0, iq, "critical"))
            continue
        if e and not h:
            diffs.append(StateDifference(sid, "unexpected_position", 0.0, eq, eq, "critical"))
            continue
        if abs(iq - eq) > cfg.qty_tol:
            diffs.append(StateDifference(sid, "wrong_quantity", iq, eq, iq - eq, "critical"))
        # price break (relative)
        ip, xp = h.price, e.market_price
        if xp > 0 and abs(ip - xp) / xp * 1e4 > cfg.price_tol_bps:
            diffs.append(StateDifference(sid, "wrong_price", ip, xp, ip - xp, "warning"))
        # cost-basis break (relative)
        icb, xcb = h.cost_basis, e.avg_cost
        if xcb > 0 and abs(icb - xcb) / xcb * 1e4 > cfg.cost_basis_tol_bps:
            diffs.append(StateDifference(sid, "wrong_cost_basis", icb, xcb, icb - xcb, "warning"))

    # cash
    cash_diff = internal.cash - external.cash
    if abs(cash_diff) > cfg.cash_tol_frac * value:
        diffs.append(StateDifference(None, "cash_mismatch", internal.cash, external.cash,
                                     cash_diff, "critical"))

    # stale orders
    for entry in (pending_orders or []):
        coid, age = entry
        if age is not None and age >= cfg.stale_order_days:
            diffs.append(StateDifference(coid, "stale_order", float(age), 0.0, float(age), "warning"))

    # duplicate / missing fills (id-set comparison)
    applied = set(applied_fill_ids or [])
    broker = set(broker_fill_ids or [])
    if len(applied_fill_ids or []) != len(applied):
        diffs.append(StateDifference(None, "duplicate_fill", len(applied_fill_ids or []),
                                     len(applied), 0.0, "critical"))
    for missing in sorted(broker - applied):
        diffs.append(StateDifference(missing, "missing_fill", 0.0, 1.0, 1.0, "critical"))

    categories: dict = {}
    for d in diffs:
        categories[d.category] = categories.get(d.category, 0) + 1

    return ReconciliationReport(
        as_of=when, ok=not diffs, differences=diffs,
        internal_cash=internal.cash, external_cash=external.cash, cash_diff=cash_diff,
        n_internal_positions=len(ih), n_external_positions=len(ep), categories=categories)

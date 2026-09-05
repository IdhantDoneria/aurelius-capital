"""Ledgers (AIDP M15).

Append-only audit stores — NOT a second accounting system. Positions, realized/
unrealized P&L and cost basis remain the reused M11 `PortfolioState`'s job; these
ledgers are the operational record of what was booked and a settlement-aware cash
*classification* on top of M11's economic cash.

  * `TradeLedger`    — every booked trade (audit).
  * `PositionLedger` — every position delta (audit; net must equal M11 holdings).
  * `CashLedger`     — every cash flow tagged with settlement status; splits M11's
                       economic cash into settled (available) vs pending (restricted).
                       Reconciles against M11: economic_balance == M11 state.cash.
"""

from __future__ import annotations

from dataclasses import replace

from mentisrex.research.post_trade.models import CashEvent, SettlementStatus


class TradeLedger:
    def __init__(self) -> None:
        self.events: list = []  # list[TradeEvent]

    def record(self, event) -> None:
        self.events.append(event)

    @property
    def n_trades(self) -> int:
        return len(self.events)

    def gross_notional(self) -> float:
        return sum(abs(e.quantity * e.price) for e in self.events)

    def net_cash_flow(self) -> float:
        return sum(-(e.quantity * e.price) - e.cost for e in self.events)


class PositionLedger:
    def __init__(self) -> None:
        self.events: list = []  # list[PositionEvent]

    def record(self, event) -> None:
        self.events.append(event)

    def net_shares(self) -> dict:
        out: dict = {}
        for e in self.events:
            out[e.security_id] = out.get(e.security_id, 0.0) + e.delta_shares
        return {s: q for s, q in out.items() if abs(q) > 1e-9}


class CashLedger:
    """Settlement-aware cash view over M11's economic cash. `post` appends a flow;
    `settle` flips it to COMPLETED. Balances are pure functions of the flow list."""

    def __init__(self, initial: float) -> None:
        self.initial = float(initial)
        self.events: list = []  # list[CashEvent]

    def post(self, event: CashEvent) -> int:
        self.events.append(event)
        return len(self.events) - 1

    def settle(self, idx: int) -> None:
        self.events[idx] = replace(self.events[idx], status=SettlementStatus.COMPLETED)

    def fail(self, idx: int) -> None:
        self.events[idx] = replace(self.events[idx], status=SettlementStatus.FAILED)

    # ── balances ──────────────────────────────────────────────────────────────
    def economic_balance(self) -> float:
        """Trade-date cash: every flow counts. Must equal M11 state.cash."""
        return self.initial + sum(e.amount for e in self.events)

    def settled_balance(self) -> float:
        return self.initial + sum(
            e.amount for e in self.events if e.status == SettlementStatus.COMPLETED
        )

    def pending_inflows(self) -> float:
        return sum(
            e.amount for e in self.events if e.status == SettlementStatus.PENDING and e.amount > 0
        )

    def pending_outflows(self) -> float:
        return sum(
            -e.amount for e in self.events if e.status == SettlementStatus.PENDING and e.amount < 0
        )

    def available(self) -> float:
        """Conservative: only settled cash is available to spend."""
        return self.settled_balance()

    def restricted(self) -> float:
        return self.pending_outflows()

    def reconciles(self, economic_ref: float, tol: float = 1e-6) -> bool:
        return abs(self.economic_balance() - economic_ref) < tol

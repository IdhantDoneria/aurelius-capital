"""Accounting adapter (AIDP M15).

Thin adapter over the *reused* M11 `PortfolioState`. Trade booking is M11's
`apply_fill` verbatim — positions, cash, realized P&L, and cost basis are computed by
the same certified accounting the simulation and paper-trading books use. NOT a second
accounting system.

The only genuinely new operations are corporate-action position adjustments (split /
merger / rename / liquidation), which M11 has no notion of. These reconstruct M11's
frozen `Holding` — using M11's own model, still no re-implemented P&L.
"""

from __future__ import annotations

from datetime import date

from mentisrex.research.simulation.models import Holding
from mentisrex.research.simulation.state import PortfolioState


class PostTradeAccounting:
    def __init__(self, initial_capital: float) -> None:
        self.state = PortfolioState(initial_capital)

    # ── trade booking (pure M11) ────────────────────────────────────────────────
    def book(self, security_id: str, quantity: float, price: float, cost: float,
             *, when: date | None = None) -> float:
        """Book a fill. Returns realized P&L on this fill (M11)."""
        return self.state.apply_fill(security_id, quantity, price, cost, when=when)

    def mark(self, prices: dict) -> None:
        self.state.mark(prices)

    # ── views ───────────────────────────────────────────────────────────────────
    @property
    def cash(self) -> float:
        return self.state.cash

    def value(self) -> float:
        return self.state.total_value()

    def realized_pnl(self) -> float:
        return self.state.realized_pnl_total

    def unrealized_pnl(self) -> float:
        return self.state.unrealized_pnl()

    def shares(self, security_id: str) -> float:
        h = self.state.holdings.get(security_id)
        return h.shares if h else 0.0

    # ── corporate-action position ops (new; M11 has none) ───────────────────────
    def adjust_split(self, security_id: str, ratio: float) -> None:
        """Split/reverse-split: shares × ratio, cost basis and mark ÷ ratio. Position
        market value and total cost are invariant — no cash, no realized P&L."""
        h = self.state.holdings.get(security_id)
        if h is None or ratio <= 0:
            return
        self.state.holdings[security_id] = Holding(
            security_id=security_id, shares=h.shares * ratio, cost_basis=h.cost_basis / ratio,
            price=h.price / ratio, realized_pnl=h.realized_pnl, opened_at=h.opened_at)

    def add_shares(self, security_id: str, extra_shares: float) -> None:
        """Stock dividend: extra shares at zero incremental cost (cost basis diluted)."""
        h = self.state.holdings.get(security_id)
        if h is None or extra_shares == 0:
            return
        new_shares = h.shares + extra_shares
        new_cb = (h.cost_basis * h.shares) / new_shares if new_shares else 0.0
        self.state.holdings[security_id] = Holding(
            security_id=security_id, shares=new_shares, cost_basis=new_cb,
            price=h.price, realized_pnl=h.realized_pnl, opened_at=h.opened_at)

    def rename(self, old_id: str, new_id: str) -> None:
        h = self.state.holdings.pop(old_id, None)
        if h is None:
            return
        self.state.holdings[new_id] = Holding(
            security_id=new_id, shares=h.shares, cost_basis=h.cost_basis, price=h.price,
            realized_pnl=h.realized_pnl, opened_at=h.opened_at)

    def close_position(self, security_id: str, price: float, *, when: date | None = None) -> float:
        """Liquidate a position at `price` (delisting/merger cash-out) via an M11 fill,
        so realized P&L and cash are booked by certified accounting. Returns realized."""
        h = self.state.holdings.get(security_id)
        if h is None:
            return 0.0
        return self.state.apply_fill(security_id, -h.shares, price, 0.0, when=when)

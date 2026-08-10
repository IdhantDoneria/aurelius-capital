"""Derivative position accounting overlay (AIDP M17).

Adapters around positions, NOT a second accounting system. Equities stay in the M11
`PortfolioState` untouched; derivatives (which M11 was never built for — margin, contract
multipliers, premium) get an in-memory `DerivativePosition` that tracks signed quantity,
average entry, realized P&L and mark. Cash still flows through the reused M15 ledger — this
class computes *what* to post, `lifecycle.InstrumentBook` posts it.

Average-cost, sign-aware realization (same convention as M11's equity accounting), so a
crossing trade realizes the closed portion and re-bases the remainder.
"""

from __future__ import annotations

from aurelius.research.instruments.models import Instrument, InstrumentPosition


class DerivativePosition:
    def __init__(self, inst: Instrument) -> None:
        self.inst = inst
        self.quantity = 0.0
        self.avg_price = 0.0
        self.last_mark = 0.0
        self.realized_pnl = 0.0
        self.margin = 0.0
        self.collateral = 0.0

    def apply(self, quantity: float, price: float) -> float:
        """Book a signed fill; return realized P&L delta (contract-scaled)."""
        cs = self.inst.contract_size
        q0, realized = self.quantity, 0.0
        if q0 == 0 or (q0 > 0) == (quantity > 0):
            # opening or increasing → weighted-average the entry price
            new_q = q0 + quantity
            self.avg_price = (self.avg_price * q0 + price * quantity) / new_q if new_q else 0.0
            self.quantity = new_q
        else:
            closed = min(abs(quantity), abs(q0)) * (1 if quantity > 0 else -1)  # signed reduction
            realized = (price - self.avg_price) * (-closed) * cs
            self.realized_pnl += realized
            self.quantity = q0 + quantity
            if (self.quantity > 0) != (q0 > 0) and self.quantity != 0:
                self.avg_price = price                     # flipped through zero → new basis
            elif self.quantity == 0:
                self.avg_price = 0.0
        self.last_mark = price
        return realized

    def mark(self, mark: float) -> float:
        """Update the mark; return variation-margin cash delta since the last mark."""
        vm = (mark - self.last_mark) * self.quantity * self.inst.contract_size
        self.last_mark = mark
        return vm

    def snapshot(self) -> InstrumentPosition:
        return InstrumentPosition(
            instrument_id=self.inst.instrument_id, quantity=self.quantity,
            avg_price=self.avg_price, last_mark=self.last_mark,
            contract_size=self.inst.contract_size, currency=self.inst.currency,
            realized_pnl=self.realized_pnl, margin=self.margin, collateral=self.collateral)

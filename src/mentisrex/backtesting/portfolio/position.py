"""Per-symbol position state.

All arithmetic uses Decimal for exact financial precision.
Float math on millions of trades introduces compounding rounding errors
that can make a losing strategy look marginally profitable.

Accounting method: weighted average cost basis.
  - Buys increase quantity and update avg_cost via weighted average.
  - Sells decrease quantity and realize P&L = (exit_price - avg_cost) x sold_qty.
  - Selling past zero (going short) resets avg_cost to the short entry price.
"""

from dataclasses import dataclass
from decimal import Decimal


@dataclass
class Position:
    symbol: str
    quantity: Decimal = Decimal("0")  # positive = long, negative = short
    avg_cost: Decimal = Decimal("0")  # average entry price per share
    realized_pnl: Decimal = Decimal("0")
    last_price: Decimal = Decimal("0")  # updated on each MarketEvent

    @property
    def market_value(self) -> Decimal:
        return self.quantity * self.last_price

    @property
    def unrealized_pnl(self) -> Decimal:
        if self.quantity == 0:
            return Decimal("0")
        return (self.last_price - self.avg_cost) * self.quantity

    @property
    def cost_basis(self) -> Decimal:
        return abs(self.quantity) * self.avg_cost

    @property
    def is_long(self) -> bool:
        return self.quantity > 0

    @property
    def is_short(self) -> bool:
        return self.quantity < 0

    @property
    def is_flat(self) -> bool:
        return self.quantity == 0

    def apply_buy(self, quantity: Decimal, price: Decimal) -> None:
        """Add to long (or cover short) at given price."""
        if quantity <= 0:
            raise ValueError(f"buy quantity must be positive, got {quantity}")

        if self.quantity < 0:
            # Covering a short
            cover_qty = min(quantity, -self.quantity)
            self.realized_pnl += (self.avg_cost - price) * cover_qty
            remainder = quantity - cover_qty
            self.quantity += cover_qty
            if remainder > 0:
                # Crossed zero — now long
                self.avg_cost = price
                self.quantity += remainder
        else:
            # Adding to long or opening new long
            total_cost = self.avg_cost * self.quantity + price * quantity
            self.quantity += quantity
            self.avg_cost = total_cost / self.quantity

    def apply_sell(self, quantity: Decimal, price: Decimal) -> None:
        """Reduce long (or add to short) at given price."""
        if quantity <= 0:
            raise ValueError(f"sell quantity must be positive, got {quantity}")

        if self.quantity > 0:
            # Reducing / closing long
            sell_qty = min(quantity, self.quantity)
            self.realized_pnl += (price - self.avg_cost) * sell_qty
            remainder = quantity - sell_qty
            self.quantity -= sell_qty
            if remainder > 0:
                # Crossed zero — now short
                self.avg_cost = price
                self.quantity -= remainder
        else:
            # Adding to short or opening new short
            total_cost = self.avg_cost * abs(self.quantity) + price * quantity
            self.quantity -= quantity
            self.avg_cost = total_cost / abs(self.quantity)

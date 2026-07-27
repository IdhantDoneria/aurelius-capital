"""Order domain objects — separate from OrderEvent (which is an event).

OrderRecord is the mutable tracking record for a submitted order.
OrderEvent is the immutable event that created it.

This distinction matters for the OMS audit trail: we need to track
partial fills, status transitions, and fill price averages across
events that may span multiple bars.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from aurelius.backtesting.events.types import OrderEvent, OrderType, Side


class OrderStatus(StrEnum):
    PENDING = "pending"
    SUBMITTED = "submitted"
    PARTIAL = "partial"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


@dataclass
class Order:
    """The OMS's view of an order — tracks lifecycle and fill progress."""

    order_id: str
    symbol: str
    order_type: OrderType
    side: Side
    quantity: Decimal
    limit_price: Decimal | None
    stop_price: Decimal | None
    strategy_id: str
    submitted_at: datetime
    status: OrderStatus = OrderStatus.PENDING

    filled_quantity: Decimal = Decimal("0")
    avg_fill_price: Decimal = Decimal("0")
    rejection_reason: str = ""

    @property
    def remaining_quantity(self) -> Decimal:
        return self.quantity - self.filled_quantity

    @property
    def is_complete(self) -> bool:
        return self.status in (
            OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED
        )

    def apply_partial_fill(self, qty: Decimal, price: Decimal) -> None:
        total_value = self.avg_fill_price * self.filled_quantity + price * qty
        self.filled_quantity += qty
        self.avg_fill_price = total_value / self.filled_quantity
        if self.filled_quantity >= self.quantity:
            self.status = OrderStatus.FILLED
        else:
            self.status = OrderStatus.PARTIAL

    @classmethod
    def from_event(cls, event: OrderEvent) -> "Order":
        return cls(
            order_id=event.order_id,
            symbol=event.symbol,
            order_type=event.order_type,
            side=event.side,
            quantity=event.quantity,
            limit_price=event.limit_price,
            stop_price=event.stop_price,
            strategy_id=event.strategy_id,
            submitted_at=event.timestamp,
        )


# Alias for clarity in reports
OrderRecord = Order

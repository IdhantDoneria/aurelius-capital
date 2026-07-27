"""OrderManager — full lifecycle tracking for every order.

Every OrderEvent submitted to the system gets a corresponding Order record.
This is the canonical audit trail: submitted → partial → filled / cancelled / rejected.

Consumers (reports, analytics) query this to reconstruct the full trade history.
"""

from aurelius.backtesting.events.types import FillEvent, OrderEvent
from aurelius.backtesting.oms.order import Order, OrderStatus


class OrderManager:
    def __init__(self) -> None:
        self._orders: dict[str, Order] = {}

    def submit(self, event: OrderEvent) -> Order:
        order = Order.from_event(event)
        order.status = OrderStatus.SUBMITTED
        self._orders[order.order_id] = order
        return order

    def apply_fill(self, fill: FillEvent) -> Order | None:
        order = self._orders.get(fill.order_id)
        if order is None:
            return None
        order.apply_partial_fill(fill.quantity, fill.fill_price)
        return order

    def cancel(self, order_id: str) -> None:
        if order := self._orders.get(order_id):
            order.status = OrderStatus.CANCELLED

    def reject(self, event: OrderEvent, reason: str) -> Order:
        order = Order.from_event(event)
        order.status = OrderStatus.REJECTED
        order.rejection_reason = reason
        self._orders[order.order_id] = order
        return order

    # ── queries ──────────────────────────────────────────────────────────────

    def get(self, order_id: str) -> Order | None:
        return self._orders.get(order_id)

    @property
    def all_orders(self) -> list[Order]:
        return list(self._orders.values())

    @property
    def filled_orders(self) -> list[Order]:
        return [o for o in self._orders.values() if o.status == OrderStatus.FILLED]

    @property
    def pending_orders(self) -> list[Order]:
        return [o for o in self._orders.values()
                if o.status in (OrderStatus.SUBMITTED, OrderStatus.PARTIAL)]

    @property
    def rejected_orders(self) -> list[Order]:
        return [o for o in self._orders.values() if o.status == OrderStatus.REJECTED]

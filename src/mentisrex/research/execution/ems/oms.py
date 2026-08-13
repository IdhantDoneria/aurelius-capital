"""Order Management System (AIDP M14).

Owns the order lifecycle and its immutable audit trail. One mutable `_ManagedOrder`
per order lives inside the OMS; every state change appends a frozen `OrderEvent` to
an append-only log (the audit trail — never mutated, never reordered, monotonically
sequenced). Illegal transitions raise `OMSError` rather than silently corrupting
state. The OMS knows nothing about brokers or algorithms — the EMS drives it.

Lifecycle:
  NEW → VALIDATED → APPROVED → SUBMITTED → ACKNOWLEDGED
      → PARTIALLY_FILLED* → FILLED
  any non-terminal → REJECTED | CANCELLED (via PENDING_CANCEL) | EXPIRED
"""

from __future__ import annotations

from datetime import date

from mentisrex.research.execution.ems.models import (
    TERMINAL,
    ExecutionReport,
    OrderEvent,
    OrderRequest,
    OrderStatus,
)
from mentisrex.research.execution.ems.slippage import arrival_slippage_bps

_FILL_TOL = 1e-6

# allowed source-states for each transition
_ALLOWED = {
    "validate": {OrderStatus.NEW},
    "approve": {OrderStatus.VALIDATED},
    "submit": {OrderStatus.APPROVED},
    "acknowledge": {OrderStatus.SUBMITTED},
    "fill": {OrderStatus.SUBMITTED, OrderStatus.ACKNOWLEDGED, OrderStatus.PARTIALLY_FILLED},
    "request_cancel": {OrderStatus.SUBMITTED, OrderStatus.ACKNOWLEDGED, OrderStatus.PARTIALLY_FILLED},
    "confirm_cancel": {OrderStatus.PENDING_CANCEL, OrderStatus.SUBMITTED,
                       OrderStatus.ACKNOWLEDGED, OrderStatus.PARTIALLY_FILLED},
    "expire": {OrderStatus.SUBMITTED, OrderStatus.ACKNOWLEDGED, OrderStatus.PARTIALLY_FILLED,
               OrderStatus.APPROVED},
}


class OMSError(Exception):
    pass


class _ManagedOrder:
    __slots__ = (
        "_notional_signed",
        "broker_order_id",
        "cost",
        "events",
        "filled_quantity",
        "fills",
        "request",
        "status",
    )

    def __init__(self, request: OrderRequest) -> None:
        self.request = request
        self.status = OrderStatus.NEW
        self.filled_quantity = 0.0
        self.cost = 0.0
        self._notional_signed = 0.0          # Σ qty*price, for avg price
        self.broker_order_id: str | None = None
        self.events: list = []
        self.fills: list = []

    @property
    def avg_fill_price(self) -> float:
        return self._notional_signed / self.filled_quantity if self.filled_quantity else 0.0


class OMS:
    def __init__(self) -> None:
        self._orders: dict = {}
        self._seq = 0

    # ── lifecycle ───────────────────────────────────────────────────────────────
    def create(self, request: OrderRequest) -> str:
        if request.order_id in self._orders:
            raise OMSError(f"duplicate order id {request.order_id!r}")
        self._orders[request.order_id] = mo = _ManagedOrder(request)
        self._emit(mo, "created", OrderStatus.NEW)
        return request.order_id

    def validate(self, order_id: str, *, ok: bool = True, reason: str = "") -> None:
        mo = self._get(order_id)
        if not ok:
            return self.reject(order_id, reason or "validation_failed")
        self._transition(mo, "validate", OrderStatus.VALIDATED, "validated")

    def approve(self, order_id: str) -> None:
        self._transition(self._get(order_id), "approve", OrderStatus.APPROVED, "approved")

    def submit(self, order_id: str, *, broker_order_id: str | None = None) -> None:
        mo = self._get(order_id)
        mo.broker_order_id = broker_order_id
        self._transition(mo, "submit", OrderStatus.SUBMITTED, f"submitted:{broker_order_id or ''}")

    def acknowledge(self, order_id: str, broker_order_id: str) -> None:
        mo = self._get(order_id)
        mo.broker_order_id = broker_order_id
        self._transition(mo, "acknowledge", OrderStatus.ACKNOWLEDGED, f"ack:{broker_order_id}")

    def record_fill(self, order_id: str, quantity: float, price: float, cost: float,
                    *, when: date | None = None, fill_id: str | None = None) -> OrderStatus:
        mo = self._get(order_id)
        self._require(mo, "fill")
        mo.filled_quantity += quantity
        mo._notional_signed += quantity * price
        mo.cost += cost
        mo.fills.append({"fill_id": fill_id, "quantity": quantity, "price": price,
                         "cost": cost, "when": when})
        complete = abs(mo.filled_quantity - mo.request.quantity) < _FILL_TOL
        status = OrderStatus.FILLED if complete else OrderStatus.PARTIALLY_FILLED
        mo.status = status
        self._emit(mo, "fill" if complete else "partial_fill", status,
                   f"qty={quantity:g}@{price:g}", filled=mo.filled_quantity, when=when)
        return status

    def request_cancel(self, order_id: str) -> None:
        self._transition(self._get(order_id), "request_cancel", OrderStatus.PENDING_CANCEL,
                         "cancel_requested")

    def confirm_cancel(self, order_id: str, *, reason: str = "") -> None:
        self._transition(self._get(order_id), "confirm_cancel", OrderStatus.CANCELLED,
                         reason or "cancelled")

    def reject(self, order_id: str, reason: str) -> None:
        mo = self._get(order_id)
        if mo.status in TERMINAL:
            raise OMSError(f"{order_id}: cannot reject from terminal {mo.status.value}")
        mo.status = OrderStatus.REJECTED
        self._emit(mo, "rejected", OrderStatus.REJECTED, reason)

    def expire(self, order_id: str, *, reason: str = "expired") -> None:
        self._transition(self._get(order_id), "expire", OrderStatus.EXPIRED, reason)

    # ── views ─────────────────────────────────────────────────────────────────
    def status(self, order_id: str) -> OrderStatus:
        return self._get(order_id).status

    def history(self, order_id: str) -> list:
        return list(self._get(order_id).events)

    def all_events(self) -> list:
        out = [e for mo in self._orders.values() for e in mo.events]
        return sorted(out, key=lambda e: e.seq)

    def order_ids(self) -> list:
        return list(self._orders)

    def report(self, order_id: str) -> ExecutionReport:
        mo = self._get(order_id)
        req = mo.request
        avg = mo.avg_fill_price
        slip = arrival_slippage_bps(avg, req.arrival_price, mo.filled_quantity)
        notional = abs(mo.filled_quantity * avg)
        is_bps = (((avg - req.arrival_price) * mo.filled_quantity + mo.cost) / notional * 1e4) \
            if notional > 0 else 0.0
        n_children = len({f["fill_id"] for f in mo.fills if f["fill_id"]}) or len(mo.fills)
        return ExecutionReport(
            order_id=order_id, security_id=req.security_id,
            requested_quantity=req.quantity, filled_quantity=mo.filled_quantity,
            avg_fill_price=avg, arrival_price=req.arrival_price, total_cost=mo.cost,
            status=mo.status, slippage_bps=slip, implementation_shortfall_bps=is_bps,
            n_child_orders=n_children, n_fills=len(mo.fills),
            events=list(mo.events), fills=list(mo.fills))

    def reports(self) -> list:
        return [self.report(oid) for oid in self._orders]

    # ── internals ───────────────────────────────────────────────────────────────
    def _get(self, order_id: str) -> _ManagedOrder:
        mo = self._orders.get(order_id)
        if mo is None:
            raise OMSError(f"unknown order {order_id!r}")
        return mo

    def _require(self, mo: _ManagedOrder, action: str) -> None:
        if mo.status not in _ALLOWED[action]:
            raise OMSError(f"{mo.request.order_id}: illegal {action} from {mo.status.value}")

    def _transition(self, mo, action, new_status, detail) -> None:
        self._require(mo, action)
        mo.status = new_status
        self._emit(mo, action, new_status, detail)

    def _emit(self, mo, kind, status, detail="", *, filled=0.0, when=None) -> None:
        self._seq += 1
        mo.events.append(OrderEvent(seq=self._seq, order_id=mo.request.order_id, kind=kind,
                                    status=status, detail=detail, filled_quantity=filled, when=when))

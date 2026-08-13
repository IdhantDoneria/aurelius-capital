"""EMS/OMS domain models (AIDP M14).

Frozen dataclasses only — every object surfaced to a caller is immutable. The one
mutable thing in the whole package is `_ManagedOrder` inside the OMS (the order's
live lifecycle state), exactly the pattern M11/M12 use (one mutable book, frozen
everything else). Broker acknowledgement / fill / position / account objects are
REUSED from M12 (`mentisrex.research.paper_trading.models`) — not re-declared — so
there is one canonical broker vocabulary across the platform.

"OMS" objects describe an order's lifecycle. "EMS" objects describe how an order is
sliced, scheduled, routed and executed. "Post-trade" objects (reports, metrics,
cost/slippage analysis) describe what actually happened.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum

# Reuse M12's broker vocabulary verbatim — no duplicate broker objects.
from mentisrex.research.paper_trading.models import (  # noqa: F401  (re-exported)
    BrokerAccount,
    BrokerFill,
    BrokerOrder,
    BrokerPosition,
)


class OrderStatus(str, Enum):
    """Full OMS lifecycle. Superset of M12's 6-state broker status: M12 tracks what
    the *broker* reports; the OMS additionally tracks pre-submission (NEW/VALIDATED/
    APPROVED) and cancel/expiry states it owns itself."""
    NEW = "new"
    VALIDATED = "validated"
    APPROVED = "approved"
    SUBMITTED = "submitted"
    ACKNOWLEDGED = "acknowledged"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    PENDING_CANCEL = "pending_cancel"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"


# terminal states: no further transition allowed
TERMINAL = {OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED, OrderStatus.EXPIRED}


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"          # interface only (deterministic sim fills at mark)
    TWAP = "twap"
    VWAP = "vwap"
    POV = "pov"


# ── intent / request ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class OrderIntent:
    """Portfolio-level desire, straight off a target: trade `delta_shares` of a name.
    The bridge from M10/M11 portfolio decisions into the execution layer."""
    security_id: str
    delta_shares: float                   # signed target change in shares

    @property
    def side(self) -> str:
        return "buy" if self.delta_shares > 0 else "sell" if self.delta_shares < 0 else "flat"


@dataclass(frozen=True)
class OrderRequest:
    """A concrete parent order to execute. `arrival_price` is the decision-time mark,
    captured once so implementation shortfall has a fixed benchmark."""
    order_id: str
    security_id: str
    quantity: float                       # signed
    order_type: OrderType = OrderType.MARKET
    limit_price: float | None = None
    algo: str | None = None               # override router's algo choice
    arrival_price: float = 0.0
    urgency: str = "normal"               # low | normal | high (routing hint)


# ── audit trail ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class OrderEvent:
    """One immutable entry in an order's append-only audit trail."""
    seq: int
    order_id: str
    kind: str                             # created|validated|approved|submitted|ack|
                                          # partial_fill|fill|cancel_requested|cancelled|
                                          # rejected|expired|replace
    status: OrderStatus
    detail: str = ""
    filled_quantity: float = 0.0
    when: date | None = None


@dataclass(frozen=True)
class Fill:
    """An executed (child) fill, mapped back to its parent order."""
    fill_id: str
    order_id: str                         # parent order id
    child_order_id: str
    security_id: str
    quantity: float                       # signed
    price: float
    cost: float
    when: date | None = None

    @property
    def notional(self) -> float:
        return self.quantity * self.price


@dataclass(frozen=True)
class FillEvent:
    seq: int
    fill: Fill


# ── scheduling / planning ───────────────────────────────────────────────────────

@dataclass(frozen=True)
class ScheduleSlice:
    index: int
    fraction: float                       # fraction of parent qty for this slice
    quantity: float                       # signed shares this slice


@dataclass(frozen=True)
class ExecutionSchedule:
    order_id: str
    algo: str
    slices: list                          # list[ScheduleSlice]

    @property
    def n_slices(self) -> int:
        return len(self.slices)


@dataclass(frozen=True)
class ExecutionPlan:
    order_id: str
    algo: str
    schedule: ExecutionSchedule
    child_orders: list                    # list[OrderRequest] (one per slice)


@dataclass(frozen=True)
class RoutingDecision:
    order_id: str
    broker: str
    algo: str
    reason: str
    constraints: dict = field(default_factory=dict)


# ── post-trade ──────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ExecutionReport:
    """Final per-parent-order outcome + its audit trail and fills."""
    order_id: str
    security_id: str
    requested_quantity: float
    filled_quantity: float
    avg_fill_price: float
    arrival_price: float
    total_cost: float
    status: OrderStatus
    slippage_bps: float
    implementation_shortfall_bps: float
    n_child_orders: int
    n_fills: int
    events: list = field(default_factory=list)     # list[OrderEvent]
    fills: list = field(default_factory=list)       # list[Fill]

    @property
    def fill_rate(self) -> float:
        return abs(self.filled_quantity) / abs(self.requested_quantity) if self.requested_quantity else 0.0


@dataclass(frozen=True)
class CostAnalysis:
    order_id: str
    commission: float
    spread: float
    slippage: float
    impact: float
    total_cost: float
    total_cost_bps: float
    implementation_shortfall_bps: float
    arrival_slippage_bps: float


@dataclass(frozen=True)
class ExecutionMetrics:
    """Session-level aggregate quality metrics."""
    n_orders: int
    n_filled: int
    n_partial: int
    n_rejected: int
    n_cancelled: int
    n_child_orders: int
    n_fills: int
    fill_rate: float
    total_requested_notional: float
    total_filled_notional: float
    total_cost: float
    total_cost_bps: float
    avg_slippage_bps: float
    avg_implementation_shortfall_bps: float
    alerts: list = field(default_factory=list)

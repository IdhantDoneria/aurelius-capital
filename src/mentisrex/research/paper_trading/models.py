"""Paper-trading domain models (AIDP M12).

Frozen dataclasses only. The one mutable book (internal state) is the reused M11
`PortfolioState` inside `PaperPortfolio`; everything a broker exposes and every
report surfaced to the caller is immutable. "Internal" = what Mentisrex thinks it
holds (M11 accounting). "External" = what the broker reports. Reconciliation and
drift are the difference between the two.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum


class OrderStatus(str, Enum):
    PENDING = "pending"
    SUBMITTED = "submitted"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


# ── request / broker acknowledgements ────────────────────────────────────────

@dataclass(frozen=True)
class OrderRequest:
    """What Mentisrex asks the broker to do. Signed `quantity` (delta shares)."""
    client_order_id: str
    security_id: str
    quantity: float
    order_type: str = "market"            # market | limit (limit = interface only)
    limit_price: float | None = None


@dataclass(frozen=True)
class BrokerOrder:
    """Broker acknowledgement of an OrderRequest."""
    broker_order_id: str
    client_order_id: str
    security_id: str
    quantity: float
    status: OrderStatus
    filled_quantity: float = 0.0
    avg_fill_price: float = 0.0
    submitted_at: datetime | None = None


@dataclass(frozen=True)
class BrokerFill:
    fill_id: str
    broker_order_id: str
    security_id: str
    quantity: float                       # signed executed shares
    price: float
    cost: float
    when: date | None = None


@dataclass(frozen=True)
class BrokerPosition:
    security_id: str
    quantity: float                       # signed
    avg_cost: float
    market_price: float = 0.0

    @property
    def market_value(self) -> float:
        return self.quantity * self.market_price


@dataclass(frozen=True)
class BrokerAccount:
    """External truth as reported by the broker."""
    account_id: str
    cash: float
    positions: dict                       # security_id -> BrokerPosition
    as_of: date | None = None

    def total_value(self) -> float:
        return self.cash + sum(p.market_value for p in self.positions.values())


# ── snapshots (paired internal/external) ─────────────────────────────────────

@dataclass(frozen=True)
class PositionSnapshot:
    security_id: str
    internal_qty: float
    external_qty: float
    internal_price: float
    external_price: float
    internal_cost_basis: float = 0.0
    external_cost_basis: float = 0.0


@dataclass(frozen=True)
class AccountSnapshot:
    date: date | None
    internal_cash: float
    external_cash: float
    internal_value: float
    external_value: float
    positions: list = field(default_factory=list)   # list[PositionSnapshot]


# ── reconciliation ───────────────────────────────────────────────────────────

@dataclass(frozen=True)
class StateDifference:
    security_id: str | None
    category: str          # missing_position | unexpected_position | wrong_quantity |
                           # wrong_price | cash_mismatch | stale_order | duplicate_fill |
                           # missing_fill | wrong_cost_basis
    internal: float
    external: float
    delta: float
    severity: str = "warning"             # info | warning | critical


@dataclass(frozen=True)
class ReconciliationReport:
    as_of: date | None
    ok: bool
    differences: list                     # list[StateDifference]
    internal_cash: float
    external_cash: float
    cash_diff: float
    n_internal_positions: int
    n_external_positions: int
    categories: dict = field(default_factory=dict)   # category -> count


# ── drift ────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class DriftReport:
    as_of: date | None
    weight_drift: dict                    # security_id -> |internal_w - target_w|
    max_weight_drift: float
    position_drift: float                 # gross share mismatch fraction
    cash_drift: float                     # |internal - external| / value
    execution_drift: float                # realized vs intended price, bps
    timing_drift: float                   # days between intended and actual sync
    cost_drift: float                     # |actual - expected| / expected
    alerts: list = field(default_factory=list)


# ── session bookkeeping ──────────────────────────────────────────────────────

@dataclass(frozen=True)
class ExecutionRecord:
    client_order_id: str
    broker_order_id: str | None
    security_id: str
    requested_qty: float
    filled_qty: float
    avg_price: float
    cost: float
    status: OrderStatus
    when: date | None = None


@dataclass(frozen=True)
class SyncEvent:
    seq: int
    date: date | None
    n_orders: int
    n_fills: int
    reconciled: bool
    n_drift_alerts: int
    note: str = ""


@dataclass(frozen=True)
class MonitoringReport:
    n_syncs: int
    n_reconciled: int
    reconciliation_rate: float
    max_weight_drift: float
    total_cost: float
    total_alerts: int
    consistency_ok: bool
    alerts: list = field(default_factory=list)


# ── validation / deployment ──────────────────────────────────────────────────

@dataclass(frozen=True)
class StateConsistencyReport:
    ok: bool
    ledger_reconciles: bool
    reconciliation_ok: bool
    max_drift: float
    issues: list = field(default_factory=list)


@dataclass(frozen=True)
class DeploymentReadinessReport:
    ready: bool
    verdict: str
    score: float
    reasons: list = field(default_factory=list)
    checks: dict = field(default_factory=dict)


@dataclass(frozen=True)
class PaperTradingValidationResult:
    ok: bool
    validation: dict                      # M9 ValidationReport (as dict)
    consistency: StateConsistencyReport
    deployment: DeploymentReadinessReport
    generated_at: datetime | None = None

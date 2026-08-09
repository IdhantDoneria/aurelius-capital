"""Post-trade domain models (AIDP M15).

Frozen dataclasses only. The single mutable book of record is the *reused* M11
`PortfolioState` (positions, realized/unrealized P&L, cost basis, economic cash) —
post-trade adds a timing + audit overlay (events, settlement, cash classification),
never a second accounting system. Every object surfaced here is immutable and dated,
so the whole lifecycle is replayable and point-in-time safe.

Vocabulary:
  * "economic cash" — M11 trade-date cash (authoritative, moves on the fill).
  * "settled cash"  — cash whose settlement date has passed (available to spend).
  * an event        — one immutable, sequenced fact in the append-only log.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum


class LifecycleState(str, Enum):
    """A trade's position in the post-trade pipeline."""
    RECEIVED = "received"
    BOOKED = "booked"
    POSITION_UPDATED = "position_updated"
    CASH_POSTED = "cash_posted"
    SETTLEMENT_PENDING = "settlement_pending"
    SETTLED = "settled"
    RECONCILED = "reconciled"
    PERFORMANCE_UPDATED = "performance_updated"
    FAILED = "failed"


class SettlementStatus(str, Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"


class CashType(str, Enum):
    TRADE = "trade"
    COMMISSION = "commission"
    FEE = "fee"
    INTEREST = "interest"
    DIVIDEND = "dividend"
    CORPORATE_ACTION = "corporate_action"


# ── events (append-only log entries) ─────────────────────────────────────────

@dataclass(frozen=True)
class TradeEvent:
    seq: int
    trade_id: str
    security_id: str
    quantity: float                       # signed executed shares
    price: float
    cost: float
    state: LifecycleState
    trade_date: date | None = None
    source_fill_id: str | None = None
    realized_pnl: float = 0.0
    detail: str = ""


@dataclass(frozen=True)
class PositionEvent:
    seq: int
    security_id: str
    delta_shares: float
    new_shares: float
    cost_basis: float
    trade_id: str | None = None
    when: date | None = None
    reason: str = "trade"                 # trade | corporate_action


@dataclass(frozen=True)
class CashEvent:
    seq: int
    amount: float                         # signed: +inflow / −outflow
    cash_type: CashType
    trade_date: date | None
    settle_date: date | None
    status: SettlementStatus
    security_id: str | None = None
    trade_id: str | None = None
    detail: str = ""


@dataclass(frozen=True)
class SettlementEvent:
    seq: int
    instruction_id: str
    trade_id: str
    status: SettlementStatus
    settle_date: date | None
    amount: float
    detail: str = ""


@dataclass(frozen=True)
class CorporateActionEvent:
    seq: int
    action_id: str
    action_type: str
    security_id: str
    ex_date: date | None
    cash_impact: float
    position_impact: float
    detail: str = ""


# ── settlement ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SettlementInstruction:
    instruction_id: str
    trade_id: str
    security_id: str
    quantity: float
    cash_amount: float                    # signed net cash to move at settlement
    trade_date: date | None
    settle_date: date | None
    status: SettlementStatus = SettlementStatus.PENDING


@dataclass(frozen=True)
class SettlementRecord:
    instruction_id: str
    trade_id: str
    settle_date: date | None
    completed_on: date | None
    cash_amount: float
    status: SettlementStatus
    detail: str = ""


# ── corporate actions ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class CorporateAction:
    """Base corporate action. Concrete kinds below carry their own parameters and set
    `action_type` in `__post_init__`; all are dated (`ex_date`) and identified for a
    replayable, auditable trail. `action_type` values: dividend | stock_dividend |
    split | reverse_split | merger | symbol_change | delisting | rights_issue."""
    action_id: str
    security_id: str
    action_type: str = ""
    ex_date: date | None = None
    detail: str = ""


@dataclass(frozen=True)
class DividendEvent(CorporateAction):
    amount_per_share: float = 0.0         # cash dividend per share
    stock_ratio: float = 0.0              # stock dividend: extra shares per share held

    def __post_init__(self):
        object.__setattr__(self, "action_type",
                           "stock_dividend" if self.stock_ratio else "dividend")


@dataclass(frozen=True)
class SplitEvent(CorporateAction):
    ratio: float = 1.0                    # 2.0 = 2-for-1 split; 0.5 = 1-for-2 reverse

    def __post_init__(self):
        object.__setattr__(self, "action_type",
                           "reverse_split" if self.ratio < 1 else "split")


@dataclass(frozen=True)
class MergerEvent(CorporateAction):
    new_security_id: str | None = None
    share_ratio: float = 1.0              # new shares per old share
    cash_per_share: float = 0.0

    def __post_init__(self):
        object.__setattr__(self, "action_type", "merger")


@dataclass(frozen=True)
class SymbolChangeEvent(CorporateAction):
    new_security_id: str | None = None

    def __post_init__(self):
        object.__setattr__(self, "action_type", "symbol_change")


@dataclass(frozen=True)
class DelistingEvent(CorporateAction):
    final_price: float = 0.0              # liquidation price (0 → total loss)

    def __post_init__(self):
        object.__setattr__(self, "action_type", "delisting")


# ── reports ──────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ReconciliationReport:
    as_of: date | None
    ok: bool
    differences: list = field(default_factory=list)   # list[StateDifference]-like dicts
    n_trades: int = 0
    n_settled: int = 0
    cash_diff: float = 0.0
    categories: dict = field(default_factory=dict)


@dataclass(frozen=True)
class SettlementReport:
    as_of: date | None
    n_pending: int
    n_completed: int
    n_failed: int
    pending_cash: float
    settled_cash: float
    settlement_exposure: float            # gross unsettled notional
    failed_instruction_ids: list = field(default_factory=list)


@dataclass(frozen=True)
class CashReport:
    as_of: date | None
    economic_cash: float
    settled_cash: float
    available_cash: float
    restricted_cash: float
    pending_inflows: float
    pending_outflows: float
    reconciles: bool


@dataclass(frozen=True)
class LedgerReport:
    n_trade_events: int
    n_position_events: int
    n_cash_events: int
    net_cash_flow: float
    gross_traded_notional: float
    reconciles: bool


@dataclass(frozen=True)
class CorporateActionReport:
    n_actions: int
    total_cash_impact: float
    by_type: dict = field(default_factory=dict)


@dataclass(frozen=True)
class OperationalHealthReport:
    ok: bool
    n_trades: int
    n_failed_settlements: int
    n_reconciliation_breaks: int
    settlement_completion_rate: float
    cash_reconciles: bool
    ledger_reconciles: bool
    alerts: list = field(default_factory=list)


@dataclass(frozen=True)
class PostTradeReport:
    as_of: date | None
    portfolio_value: float
    settled_cash: float
    realized_pnl: float
    unrealized_pnl: float
    n_positions: int
    settlement: SettlementReport
    cash: CashReport
    ledger: LedgerReport
    corporate_actions: CorporateActionReport
    health: OperationalHealthReport
    reconciliation: ReconciliationReport | None = None

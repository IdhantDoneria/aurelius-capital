"""Trade Lifecycle & Post-Trade Operations Engine (AIDP M15).

Transforms executed trades into fully tracked, settled, reconciled, auditable
portfolio events — closing Execution → Settlement → Accounting → Reporting.

Additive and dependency-injected: reuses M11 accounting (the single book of record),
is compatible with M12 state and M14 execution objects, and duplicates no orders,
fills, positions, risk checks, or portfolio accounting. Event-driven: every lifecycle
fact is an immutable, sequenced event, so the whole run is replayable and PIT-safe.
"""

from mentisrex.research.post_trade.accounting import PostTradeAccounting
from mentisrex.research.post_trade.cash import cash_report, settlement_obligations
from mentisrex.research.post_trade.corporate_actions import apply as apply_corporate_action
from mentisrex.research.post_trade.diagnostics import diagnostics, fingerprint
from mentisrex.research.post_trade.events import EventLog
from mentisrex.research.post_trade.ledger import CashLedger, PositionLedger, TradeLedger
from mentisrex.research.post_trade.lifecycle import PostTradeEngine
from mentisrex.research.post_trade.models import (
    CashEvent,
    CashReport,
    CashType,
    CorporateAction,
    CorporateActionEvent,
    CorporateActionReport,
    DelistingEvent,
    DividendEvent,
    LedgerReport,
    LifecycleState,
    MergerEvent,
    OperationalHealthReport,
    PositionEvent,
    PostTradeReport,
    ReconciliationReport,
    SettlementEvent,
    SettlementInstruction,
    SettlementRecord,
    SettlementReport,
    SettlementStatus,
    SplitEvent,
    SymbolChangeEvent,
    TradeEvent,
)
from mentisrex.research.post_trade.monitoring import ledger_reconciles, operational_health
from mentisrex.research.post_trade.performance import cost_attribution, performance
from mentisrex.research.post_trade.reconciliation import reconcile
from mentisrex.research.post_trade.registry import attach_post_trade
from mentisrex.research.post_trade.reporting import (
    corporate_action_report,
    ledger_report,
    post_trade_report,
    settlement_report,
)
from mentisrex.research.post_trade.settlement import (
    SettlementConfig,
    SettlementEngine,
    settlement_date,
)
from mentisrex.research.post_trade.tax import (
    JurisdictionRule,
    RealizedGain,
    TaxLot,
    TaxLotBook,
    build_from_engine,
)
from mentisrex.research.post_trade.validation import (
    ValidationResult,
    check_determinism,
    validate_engine,
    validate_fill,
)

__all__ = [
    "CashEvent",
    "CashLedger",
    "CashReport",
    "CashType",
    "CorporateAction",
    "CorporateActionEvent",
    "CorporateActionReport",
    "DelistingEvent",
    "DividendEvent",
    "EventLog",
    "JurisdictionRule",
    "LedgerReport",
    "LifecycleState",
    "MergerEvent",
    "OperationalHealthReport",
    "PositionEvent",
    "PositionLedger",
    "PostTradeAccounting",
    "PostTradeEngine",
    "PostTradeReport",
    "RealizedGain",
    "ReconciliationReport",
    "SettlementConfig",
    "SettlementEngine",
    "SettlementEvent",
    "SettlementInstruction",
    "SettlementRecord",
    "SettlementReport",
    "SettlementStatus",
    "SplitEvent",
    "SymbolChangeEvent",
    "TaxLot",
    "TaxLotBook",
    "TradeEvent",
    "TradeLedger",
    "ValidationResult",
    "apply_corporate_action",
    "attach_post_trade",
    "build_from_engine",
    "cash_report",
    "check_determinism",
    "corporate_action_report",
    "cost_attribution",
    "diagnostics",
    "fingerprint",
    "ledger_reconciles",
    "ledger_report",
    "operational_health",
    "performance",
    "post_trade_report",
    "reconcile",
    "settlement_date",
    "settlement_obligations",
    "settlement_report",
    "validate_engine",
    "validate_fill",
]

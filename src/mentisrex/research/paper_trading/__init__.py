"""Paper Trading Bridge, Live-State Reconciliation & Continuous Runtime (AIDP M12/M23).

M12: Bridges M11 simulation into a persistent live-state loop against an external
(paper) broker. Adds broker abstraction, reconciliation, drift monitoring, and
deployment-readiness validation.

M23: Adds PaperTradingLoop — a continuous, persistent, auditable paper-trading
runtime that orchestrates M22 strategy evaluation against M12 paper execution across
multiple snapshots and multiple strategies, with checkpoint/restart and performance records.

Not a live trading system: offline, deterministic, no broker network or credentials.
"""

from mentisrex.research.paper_trading.adapter import (
    AlpacaAdapter,
    BrokerAdapter,
    FIXAdapter,
    InteractiveBrokersAdapter,
    ZerodhaAdapter,
)
from mentisrex.research.paper_trading.broker import Broker, MockBroker, SimulatedBroker
from mentisrex.research.paper_trading.checkpoint import load_checkpoint, save_checkpoint
from mentisrex.research.paper_trading.cycle import (
    CycleRecord,
    ForwardPerformanceRecord,
    PaperBacktestComparison,
    PerformanceMetrics,
)
from mentisrex.research.paper_trading.diagnostics import diagnostics
from mentisrex.research.paper_trading.drift import DriftThresholds, compute_drift
from mentisrex.research.paper_trading.loop import (
    CostCompatibilityResult,
    LoopConfig,
    LoopCycleResult,
    LoopError,
    PaperTradingLoop,
    StrategyCycleResult,
    check_cost_compatibility,
)
from mentisrex.research.paper_trading.models import (
    AccountSnapshot,
    BrokerAccount,
    BrokerFill,
    BrokerOrder,
    BrokerPosition,
    DeploymentReadinessReport,
    DriftReport,
    ExecutionRecord,
    MonitoringReport,
    OrderRequest,
    OrderStatus,
    PaperTradingValidationResult,
    PositionSnapshot,
    ReconciliationReport,
    StateConsistencyReport,
    StateDifference,
    SyncEvent,
)
from mentisrex.research.paper_trading.monitoring import monitoring_report
from mentisrex.research.paper_trading.portfolio import PaperPortfolio
from mentisrex.research.paper_trading.reconciliation import ReconciliationConfig, reconcile
from mentisrex.research.paper_trading.registry import attach_session
from mentisrex.research.paper_trading.risk import PreTradeRiskGate, RiskLimits
from mentisrex.research.paper_trading.runtime_state import StrategyRuntimeState
from mentisrex.research.paper_trading.scheduler import (
    Clock,
    FixedClock,
    RebalanceScheduler,
)
from mentisrex.research.paper_trading.session import PaperTradingSession, SessionConfig
from mentisrex.research.paper_trading.validation import (
    deployment_readiness,
    state_consistency,
    validate_session,
)

__all__ = [
    "AccountSnapshot",
    "AlpacaAdapter",
    "Broker",
    "BrokerAccount",
    "BrokerAdapter",
    "BrokerFill",
    "BrokerOrder",
    "BrokerPosition",
    "Clock",
    "CostCompatibilityResult",
    "CycleRecord",
    "DeploymentReadinessReport",
    "DriftReport",
    "DriftThresholds",
    "ExecutionRecord",
    "FIXAdapter",
    "FixedClock",
    "ForwardPerformanceRecord",
    "InteractiveBrokersAdapter",
    "LoopConfig",
    "LoopCycleResult",
    "LoopError",
    "MockBroker",
    "MonitoringReport",
    "OrderRequest",
    "OrderStatus",
    "PaperBacktestComparison",
    "PaperPortfolio",
    # M23 — Continuous Paper Trading Runtime
    "PaperTradingLoop",
    "PaperTradingSession",
    "PaperTradingValidationResult",
    "PerformanceMetrics",
    "PositionSnapshot",
    "PreTradeRiskGate",
    "RebalanceScheduler",
    "ReconciliationConfig",
    "ReconciliationReport",
    "RiskLimits",
    "SessionConfig",
    "SimulatedBroker",
    "StateConsistencyReport",
    "StateDifference",
    "StrategyCycleResult",
    "StrategyRuntimeState",
    "SyncEvent",
    "ZerodhaAdapter",
    "attach_session",
    "check_cost_compatibility",
    "compute_drift",
    "deployment_readiness",
    "diagnostics",
    "load_checkpoint",
    "monitoring_report",
    "reconcile",
    "save_checkpoint",
    "state_consistency",
    "validate_session",
]

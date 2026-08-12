"""Paper Trading Bridge, Live-State Reconciliation & Continuous Runtime (AIDP M12/M23).

M12: Bridges M11 simulation into a persistent live-state loop against an external
(paper) broker. Adds broker abstraction, reconciliation, drift monitoring, and
deployment-readiness validation.

M23: Adds PaperTradingLoop — a continuous, persistent, auditable paper-trading
runtime that orchestrates M22 strategy evaluation against M12 paper execution across
multiple snapshots and multiple strategies, with checkpoint/restart and performance records.

Not a live trading system: offline, deterministic, no broker network or credentials.
"""

from aurelius.research.paper_trading.adapter import (
    AlpacaAdapter,
    BrokerAdapter,
    FIXAdapter,
    InteractiveBrokersAdapter,
    ZerodhaAdapter,
)
from aurelius.research.paper_trading.broker import Broker, MockBroker, SimulatedBroker
from aurelius.research.paper_trading.diagnostics import diagnostics
from aurelius.research.paper_trading.drift import DriftThresholds, compute_drift
from aurelius.research.paper_trading.models import (
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
from aurelius.research.paper_trading.monitoring import monitoring_report
from aurelius.research.paper_trading.portfolio import PaperPortfolio
from aurelius.research.paper_trading.reconciliation import ReconciliationConfig, reconcile
from aurelius.research.paper_trading.checkpoint import load_checkpoint, save_checkpoint
from aurelius.research.paper_trading.cycle import (
    CycleRecord,
    ForwardPerformanceRecord,
    PaperBacktestComparison,
    PerformanceMetrics,
)
from aurelius.research.paper_trading.loop import (
    CostCompatibilityResult,
    LoopConfig,
    LoopCycleResult,
    LoopError,
    PaperTradingLoop,
    StrategyCycleResult,
    check_cost_compatibility,
)
from aurelius.research.paper_trading.registry import attach_session
from aurelius.research.paper_trading.runtime_state import StrategyRuntimeState
from aurelius.research.paper_trading.scheduler import (
    Clock,
    FixedClock,
    RebalanceScheduler,
)
from aurelius.research.paper_trading.risk import PreTradeRiskGate, RiskLimits
from aurelius.research.paper_trading.session import PaperTradingSession, SessionConfig
from aurelius.research.paper_trading.validation import (
    deployment_readiness,
    state_consistency,
    validate_session,
)

__all__ = [
    "Broker", "MockBroker", "SimulatedBroker",
    "BrokerAdapter", "InteractiveBrokersAdapter", "AlpacaAdapter", "ZerodhaAdapter", "FIXAdapter",
    "PaperTradingSession", "SessionConfig", "PaperPortfolio",
    "reconcile", "ReconciliationConfig", "compute_drift", "DriftThresholds",
    "PreTradeRiskGate", "RiskLimits", "monitoring_report", "diagnostics",
    "attach_session", "validate_session", "state_consistency", "deployment_readiness",
    "OrderRequest", "OrderStatus", "BrokerOrder", "BrokerFill", "BrokerPosition", "BrokerAccount",
    "PositionSnapshot", "AccountSnapshot", "ReconciliationReport", "StateDifference",
    "DriftReport", "SyncEvent", "ExecutionRecord", "MonitoringReport",
    "PaperTradingValidationResult", "DeploymentReadinessReport", "StateConsistencyReport",
    # M23 — Continuous Paper Trading Runtime
    "PaperTradingLoop", "LoopConfig", "LoopCycleResult", "StrategyCycleResult", "LoopError",
    "check_cost_compatibility", "CostCompatibilityResult",
    "StrategyRuntimeState",
    "Clock", "FixedClock", "RebalanceScheduler",
    "CycleRecord", "ForwardPerformanceRecord", "PerformanceMetrics", "PaperBacktestComparison",
    "save_checkpoint", "load_checkpoint",
]

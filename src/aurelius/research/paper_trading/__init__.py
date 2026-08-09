"""Paper Trading Bridge & Live-State Reconciliation (AIDP M12).

Bridges the M11 simulation into a persistent live-state loop against an external
(paper) broker. Reuses the M11 accounting core, order sizing, execution/cost
interfaces, and the M9 validation gate — nothing is duplicated. Adds: a broker
abstraction (offline Mock/Simulated + real-adapter interfaces), internal↔external
reconciliation, drift monitoring, and deployment-readiness validation.

Not a live trading system: offline, deterministic, no broker network or creds.
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
from aurelius.research.paper_trading.registry import attach_session
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
]

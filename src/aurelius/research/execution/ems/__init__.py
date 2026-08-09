"""Execution Management System & Order Management System (AIDP M14).

Transforms approved portfolio decisions into controlled, auditable, replayable
execution. Additive and dependency-injected: reuses M10 costs, M11 Order/accounting,
M12 brokers/reconciliation/book, and the M13 risk gate — no duplicate accounting,
no duplicate risk checks, no broker coupling.

Nested under `execution/` (M8 owns `execution/*.py`) as `execution.ems` so it is
purely additive to the certified M8 research-execution package.

Pipeline: parent orders → M13 risk gate → OMS → router → algorithm → broker →
fills → M12 book → post-trade analytics.
"""

from aurelius.research.execution.ems.adapter import (
    AlpacaAdapter,
    BrokerAdapter,
    FIXAdapter,
    InteractiveBrokersAdapter,
    ZerodhaAdapter,
)
from aurelius.research.execution.ems.algorithms import (
    ExecutionAlgorithm,
    available,
    get_algorithm,
)
from aurelius.research.execution.ems.broker import (
    ExecutionBroker,
    MockExecutionBroker,
    SimulatedExecutionBroker,
)
from aurelius.research.execution.ems.diagnostics import diagnostics, fingerprint
from aurelius.research.execution.ems.ems import EMS, ExecutionConfig, ExecutionSession
from aurelius.research.execution.ems.execution_algorithms import POV, TWAP, VWAP, ImmediateExecution
from aurelius.research.execution.ems.fills import FillProcessor
from aurelius.research.execution.ems.models import (
    BrokerAccount,
    BrokerFill,
    BrokerOrder,
    BrokerPosition,
    CostAnalysis,
    ExecutionMetrics,
    ExecutionPlan,
    ExecutionReport,
    ExecutionSchedule,
    Fill,
    FillEvent,
    OrderEvent,
    OrderIntent,
    OrderRequest,
    OrderStatus,
    OrderType,
    RoutingDecision,
    ScheduleSlice,
)
from aurelius.research.execution.ems.monitoring import by_algorithm, by_broker, metrics
from aurelius.research.execution.ems.oms import OMS, OMSError
from aurelius.research.execution.ems.orders import (
    MarketInfo,
    build_request,
    build_requests,
    intents_from_target,
    limit_order,
    market_order,
    pov_order,
    stop_order,
    to_sim_orders,
    twap_order,
    vwap_order,
)
from aurelius.research.execution.ems.reconciliation import (
    ExecutionReconciliationReport,
    reconcile_execution,
    reconcile_state,
)
from aurelius.research.execution.ems.registry import attach_execution
from aurelius.research.execution.ems.router import ExecutionRouter
from aurelius.research.execution.ems.transaction_costs import attribute
from aurelius.research.execution.ems.validation import (
    ValidationResult,
    check_determinism,
    validate_request,
    validate_session,
)

__all__ = [
    "EMS",
    "OMS",
    "POV",
    "TWAP",
    "VWAP",
    "AlpacaAdapter",
    "BrokerAccount",
    "BrokerAdapter",
    "BrokerFill",
    "BrokerOrder",
    "BrokerPosition",
    "CostAnalysis",
    "ExecutionAlgorithm",
    "ExecutionBroker",
    "ExecutionConfig",
    "ExecutionMetrics",
    "ExecutionPlan",
    "ExecutionReconciliationReport",
    "ExecutionReport",
    "ExecutionRouter",
    "ExecutionSchedule",
    "ExecutionSession",
    "FIXAdapter",
    "Fill",
    "FillEvent",
    "FillProcessor",
    "ImmediateExecution",
    "InteractiveBrokersAdapter",
    "MarketInfo",
    "MockExecutionBroker",
    "OMSError",
    "OrderEvent",
    "OrderIntent",
    "OrderRequest",
    "OrderStatus",
    "OrderType",
    "RoutingDecision",
    "ScheduleSlice",
    "SimulatedExecutionBroker",
    "ValidationResult",
    "ZerodhaAdapter",
    "attach_execution",
    "attribute",
    "available",
    "build_request",
    "build_requests",
    "by_algorithm",
    "by_broker",
    "check_determinism",
    "diagnostics",
    "fingerprint",
    "get_algorithm",
    "intents_from_target",
    "limit_order",
    "market_order",
    "metrics",
    "pov_order",
    "reconcile_execution",
    "reconcile_state",
    "stop_order",
    "to_sim_orders",
    "twap_order",
    "validate_request",
    "validate_session",
    "vwap_order",
]

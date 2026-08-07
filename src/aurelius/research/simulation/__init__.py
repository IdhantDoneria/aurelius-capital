"""Institutional Multi-Period Portfolio Simulation Engine (AIDP Phase 11).

Evolves optimized (Phase 10) portfolios into a multi-year investment history:
persistent holdings, exact cash accounting, transaction costs, rebalancing, and
institutional analytics. Never reruns research — the alpha/portfolio engines are
injected as providers.
"""

from aurelius.research.simulation.engine import PortfolioSimulationEngine, SimulationConfig
from aurelius.research.simulation.execution import (
    CostExecutionModel,
    ExecutionModel,
    FrictionlessExecutionModel,
)
from aurelius.research.simulation.orders import SizingConfig, generate_orders
from aurelius.research.simulation.rebalancing import RebalancePolicy, calendar_dates
from aurelius.research.simulation.registry import attach_simulation
from aurelius.research.simulation.state import PortfolioState
from aurelius.research.simulation.validation import to_performance_metrics, validate_simulation

__all__ = [
    "PortfolioSimulationEngine", "SimulationConfig", "PortfolioState",
    "ExecutionModel", "CostExecutionModel", "FrictionlessExecutionModel",
    "SizingConfig", "generate_orders", "RebalancePolicy", "calendar_dates",
    "attach_simulation", "validate_simulation", "to_performance_metrics",
]

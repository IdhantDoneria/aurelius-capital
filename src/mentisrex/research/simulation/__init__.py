"""Institutional Multi-Period Portfolio Simulation Engine (AIDP M11).

Evolves optimized (M10) portfolios into a multi-year investment history:
persistent holdings, exact cash accounting, transaction costs, rebalancing, and
institutional analytics. Never reruns research — the alpha/portfolio engines are
injected as providers.
"""

from mentisrex.research.simulation.engine import PortfolioSimulationEngine, SimulationConfig
from mentisrex.research.simulation.execution import (
    CostExecutionModel,
    ExecutionModel,
    FrictionlessExecutionModel,
)
from mentisrex.research.simulation.orders import SizingConfig, generate_orders
from mentisrex.research.simulation.rebalancing import RebalancePolicy, calendar_dates
from mentisrex.research.simulation.registry import attach_simulation
from mentisrex.research.simulation.state import PortfolioState
from mentisrex.research.simulation.validation import to_performance_metrics, validate_simulation

__all__ = [
    "PortfolioSimulationEngine", "SimulationConfig", "PortfolioState",
    "ExecutionModel", "CostExecutionModel", "FrictionlessExecutionModel",
    "SizingConfig", "generate_orders", "RebalancePolicy", "calendar_dates",
    "attach_simulation", "validate_simulation", "to_performance_metrics",
]

"""Portfolio solvers (AIDP Phase 10) — dependency-injected optimizer implementations."""

from aurelius.research.portfolio.solvers.base import Solver
from aurelius.research.portfolio.solvers.equal_weight import EqualWeightSolver
from aurelius.research.portfolio.solvers.max_diversification import MaxDiversificationSolver
from aurelius.research.portfolio.solvers.mean_variance import (
    MaxSharpeSolver,
    MinVarianceSolver,
    TrackingErrorSolver,
)
from aurelius.research.portfolio.solvers.risk_parity import (
    HierarchicalRiskParitySolver,
    RiskParitySolver,
)

# objective name → default solver
SOLVER_REGISTRY: dict[str, type[Solver]] = {
    "equal_weight": EqualWeightSolver,
    "max_sharpe": MaxSharpeSolver,
    "min_variance": MinVarianceSolver,
    "risk_parity": RiskParitySolver,
    "max_diversification": MaxDiversificationSolver,
    "tracking_error": TrackingErrorSolver,
}

__all__ = [
    "SOLVER_REGISTRY", "Solver", "EqualWeightSolver", "MaxSharpeSolver",
    "MinVarianceSolver", "RiskParitySolver", "MaxDiversificationSolver",
    "TrackingErrorSolver", "HierarchicalRiskParitySolver",
]

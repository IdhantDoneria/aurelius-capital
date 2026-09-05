"""Portfolio solvers (AIDP M10) — dependency-injected optimizer implementations."""

from mentisrex.research.portfolio.solvers.base import Solver
from mentisrex.research.portfolio.solvers.equal_weight import EqualWeightSolver
from mentisrex.research.portfolio.solvers.max_diversification import MaxDiversificationSolver
from mentisrex.research.portfolio.solvers.mean_variance import (
    MaxSharpeSolver,
    MinVarianceSolver,
    TrackingErrorSolver,
)
from mentisrex.research.portfolio.solvers.risk_parity import (
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
    "SOLVER_REGISTRY",
    "EqualWeightSolver",
    "HierarchicalRiskParitySolver",
    "MaxDiversificationSolver",
    "MaxSharpeSolver",
    "MinVarianceSolver",
    "RiskParitySolver",
    "Solver",
    "TrackingErrorSolver",
]

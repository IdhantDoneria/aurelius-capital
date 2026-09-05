"""Institutional Portfolio Construction & Optimization Engine (AIDP M10).

Transforms validated research signals into implementable portfolios. Alpha
generation (the signal) stays strictly separate from construction (sizing, risk,
constraints, costs). Optimizer-agnostic via dependency injection.
"""

from mentisrex.research.portfolio.constraints import ConstraintSet
from mentisrex.research.portfolio.costs import TransactionCostModel
from mentisrex.research.portfolio.engine import (
    PortfolioEngine,
    record_portfolio,
    signals_from_matrix,
)
from mentisrex.research.portfolio.models import Portfolio, PortfolioPosition
from mentisrex.research.portfolio.objectives import DEFINITIONS, Objective
from mentisrex.research.portfolio.optimizer import Optimizer
from mentisrex.research.portfolio.rebalancing import RebalanceRule
from mentisrex.research.portfolio.validation import validate_portfolio

__all__ = [
    "DEFINITIONS",
    "ConstraintSet",
    "Objective",
    "Optimizer",
    "Portfolio",
    "PortfolioEngine",
    "PortfolioPosition",
    "RebalanceRule",
    "TransactionCostModel",
    "record_portfolio",
    "signals_from_matrix",
    "validate_portfolio",
]

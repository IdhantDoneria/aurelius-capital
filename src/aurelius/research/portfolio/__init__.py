"""Institutional Portfolio Construction & Optimization Engine (AIDP Phase 10).

Transforms validated research signals into implementable portfolios. Alpha
generation (the signal) stays strictly separate from construction (sizing, risk,
constraints, costs). Optimizer-agnostic via dependency injection.
"""

from aurelius.research.portfolio.constraints import ConstraintSet
from aurelius.research.portfolio.costs import TransactionCostModel
from aurelius.research.portfolio.engine import (
    PortfolioEngine,
    record_portfolio,
    signals_from_matrix,
)
from aurelius.research.portfolio.models import Portfolio, PortfolioPosition
from aurelius.research.portfolio.objectives import DEFINITIONS, Objective
from aurelius.research.portfolio.optimizer import Optimizer
from aurelius.research.portfolio.rebalancing import RebalanceRule
from aurelius.research.portfolio.validation import validate_portfolio

__all__ = [
    "ConstraintSet", "DEFINITIONS", "Objective", "Optimizer", "Portfolio",
    "PortfolioEngine", "PortfolioPosition", "RebalanceRule", "TransactionCostModel",
    "record_portfolio", "signals_from_matrix", "validate_portfolio",
]

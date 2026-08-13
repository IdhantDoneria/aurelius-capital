"""AIDP M22 — Strategy Deployment Layer.

Connects validated research artifacts to the existing Mentisrex execution and
paper-trading infrastructure. Provides:

  StrategySpecification   — immutable, versioned strategy contract
  StrategyState           — lifecycle state machine (DRAFT → … → PAPER)
  StrategyRegistry        — in-memory registry of specs and states
  StrategyRuntime         — orchestrates M10 → M13 → M14 evaluation pipeline
  DeploymentManifest      — deterministic deployment fingerprint
  ReadinessValidator      — gate: all preconditions before DEPLOYABLE/PAPER
  ConsistencyChecker      — research/deployment drift detection

This module does NOT provide a new backtesting engine, execution engine, risk
engine, portfolio construction engine, or market-data pipeline. All downstream
work is delegated to M9–M21.
"""

from mentisrex.research.strategy_deployment.consistency import ConsistencyChecker
from mentisrex.research.strategy_deployment.models import (
    ConsistencyReport,
    DeploymentManifest,
    FeatureSet,
    OrderIntentRecord,
    ReadinessReport,
    SignalRecord,
    SignalSet,
    StrategyEvaluation,
    StrategySpecification,
    StrategyState,
    StrategyType,
    make_manifest,
    make_spec,
)
from mentisrex.research.strategy_deployment.readiness import ReadinessValidator
from mentisrex.research.strategy_deployment.registry import (
    StrategyEntry,
    StrategyRegistry,
    StrategyTransitionError,
)
from mentisrex.research.strategy_deployment.runtime import (
    EvaluationError,
    StrategyLogic,
    StrategyRuntime,
)

__all__ = [
    # models
    "StrategySpecification",
    "StrategyState",
    "StrategyType",
    "FeatureSet",
    "SignalRecord",
    "SignalSet",
    "OrderIntentRecord",
    "StrategyEvaluation",
    "DeploymentManifest",
    "ReadinessReport",
    "ConsistencyReport",
    "make_spec",
    "make_manifest",
    # registry
    "StrategyRegistry",
    "StrategyEntry",
    "StrategyTransitionError",
    # runtime
    "StrategyRuntime",
    "StrategyLogic",
    "EvaluationError",
    # validators
    "ReadinessValidator",
    "ConsistencyChecker",
]

"""Forward Validation & Diagnostics Framework (AIDP M24).

M24 answers: "Was the M23 paper-trading operation correct, how did it differ
from research expectations, and what evidence explains the difference?"

M24 does NOT:
  - modify strategy parameters or configuration
  - automatically promote, retire, or allocate capital to strategies
  - create a new strategy engine, backtesting engine, paper-trading engine,
    portfolio engine, risk engine, execution engine, or market-data pipeline
  - fetch data from external providers (no Yahoo, Bloomberg, SEC, FRED, etc.)
  - implement live-money trading

Consumes:
  M23 ForwardPerformanceRecord + CycleRecords
  M22 StrategySpecification
  M9  ValidationReport (optional)
  Caller-supplied backtest results (optional)

Produces:
  ForwardValidationArtifact — immutable, fingerprinted
  ForwardValidationReport   — human+machine readable
"""

from mentisrex.research.forward_validation.engine import EngineConfig, ForwardValidationEngine
from mentisrex.research.forward_validation.errors import (
    ForwardValidationError,
    ImplementationDivergenceError,
    InsufficientDataError,
    InvalidArtifactError,
    LineageError,
    PITViolationError,
)
from mentisrex.research.forward_validation.lineage import LineageChain, build_lineage
from mentisrex.research.forward_validation.models import (
    DiagnosticRecord,
    DiagnosticSeverity,
    DiscrepancyCategory,
    EconomicStatus,
    ForwardValidationArtifact,
    ForwardValidationReport,
    OperationalStatus,
    SampleAdequacy,
    ValidationStatus,
    make_diagnostic,
    stamp_artifact,
)
from mentisrex.research.forward_validation.report import assemble_report
from mentisrex.research.forward_validation.statistics import (
    AnnualizedMetrics,
    bootstrap_mean_ci,
    compute_annualized,
    daily_returns_from_nav,
    return_distribution_summary,
    rolling_sharpe,
    rolling_volatility,
    sample_adequacy,
)

__all__ = [
    # statistics
    "AnnualizedMetrics",
    "DiagnosticRecord",
    "DiagnosticSeverity",
    "DiscrepancyCategory",
    "EconomicStatus",
    "EngineConfig",
    # models
    "ForwardValidationArtifact",
    # engine
    "ForwardValidationEngine",
    # errors
    "ForwardValidationError",
    "ForwardValidationReport",
    "ImplementationDivergenceError",
    "InsufficientDataError",
    "InvalidArtifactError",
    # lineage
    "LineageChain",
    "LineageError",
    "OperationalStatus",
    "PITViolationError",
    "SampleAdequacy",
    "ValidationStatus",
    # report
    "assemble_report",
    "bootstrap_mean_ci",
    "build_lineage",
    "compute_annualized",
    "daily_returns_from_nav",
    "make_diagnostic",
    "return_distribution_summary",
    "rolling_sharpe",
    "rolling_volatility",
    "sample_adequacy",
    "stamp_artifact",
]

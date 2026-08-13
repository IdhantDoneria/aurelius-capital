"""Phase 14: Statistical Validation & Robustness Framework.

Entry point: ValidationService.validate() takes a completed experiment
(strategy factory + bars) and returns a ComprehensiveReport containing
statistical evidence, robustness assessment, and a 5-state promotion decision.
"""

from mentisrex.validation.audit import AuditRecord, capture_environment
from mentisrex.validation.metrics import ExtendedMetrics, MetricsCalculator
from mentisrex.validation.promotion import (
    PromotionCriteria,
    PromotionDecision,
    PromotionEngine,
    PromotionState,
)
from mentisrex.validation.report import ComprehensiveReport
from mentisrex.validation.robustness import (
    RegimeStats,
    RobustnessAnalyzer,
    RobustnessAssessment,
    SensitivitySweep,
)
from mentisrex.validation.service import DataIntegrityError, ValidationService
from mentisrex.validation.stats import (
    BootstrapResult,
    PermutationResult,
    StatEngine,
)

__all__ = [
    # audit
    "AuditRecord",
    "BootstrapResult",
    # report
    "ComprehensiveReport",
    "DataIntegrityError",
    # metrics
    "ExtendedMetrics",
    "MetricsCalculator",
    "PermutationResult",
    "PromotionCriteria",
    "PromotionDecision",
    # promotion
    "PromotionEngine",
    "PromotionState",
    "RegimeStats",
    # robustness
    "RobustnessAnalyzer",
    "RobustnessAssessment",
    "SensitivitySweep",
    # stats
    "StatEngine",
    # service
    "ValidationService",
    "capture_environment",
]

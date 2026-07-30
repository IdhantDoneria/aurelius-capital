"""Phase 14: Statistical Validation & Robustness Framework.

Entry point: ValidationService.validate() takes a completed experiment
(strategy factory + bars) and returns a ComprehensiveReport containing
statistical evidence, robustness assessment, and a 5-state promotion decision.
"""

from aurelius.validation.audit import AuditRecord, capture_environment
from aurelius.validation.metrics import ExtendedMetrics, MetricsCalculator
from aurelius.validation.promotion import (
    PromotionCriteria,
    PromotionDecision,
    PromotionEngine,
    PromotionState,
)
from aurelius.validation.report import ComprehensiveReport
from aurelius.validation.robustness import (
    RegimeStats,
    RobustnessAnalyzer,
    RobustnessAssessment,
    SensitivitySweep,
)
from aurelius.validation.service import DataIntegrityError, ValidationService
from aurelius.validation.stats import (
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

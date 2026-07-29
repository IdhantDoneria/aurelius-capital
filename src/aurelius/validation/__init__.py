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
    # service
    "ValidationService",
    "DataIntegrityError",
    # report
    "ComprehensiveReport",
    # metrics
    "ExtendedMetrics",
    "MetricsCalculator",
    # stats
    "StatEngine",
    "BootstrapResult",
    "PermutationResult",
    # robustness
    "RobustnessAnalyzer",
    "RobustnessAssessment",
    "RegimeStats",
    "SensitivitySweep",
    # promotion
    "PromotionEngine",
    "PromotionDecision",
    "PromotionState",
    "PromotionCriteria",
    # audit
    "AuditRecord",
    "capture_environment",
]

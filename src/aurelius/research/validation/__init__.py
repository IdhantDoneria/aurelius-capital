"""Institutional Research Validation & Diagnostics Framework (AIDP M9).

The final quality gate between research execution and paper trading. Also re-exports
the pre-existing lightweight validation helpers (`legacy`) so historical imports
(`from aurelius.research.validation import evaluate, train_test, ...`) keep working —
this package is additive over that module, not a replacement.
"""

from aurelius.research.validation.engine import ResearchValidator, ValidationConfig
from aurelius.research.validation.quality import check
from aurelius.research.validation.report import ValidationReport

# ── backward-compatible re-exports of the former research/validation.py module ──
from aurelius.research.validation.legacy import (  # noqa: E402
    evaluate,
    parameter_sensitivity,
    rolling_validation,
    run_backtest,
    select_features,
    train_test,
    walk_forward,
)

__all__ = [
    "ResearchValidator", "ValidationConfig", "ValidationReport", "check",
    # legacy
    "evaluate", "parameter_sensitivity", "rolling_validation", "run_backtest",
    "select_features", "train_test", "walk_forward",
]

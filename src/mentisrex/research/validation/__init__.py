"""Institutional Research Validation & Diagnostics Framework (AIDP M9).

The final quality gate between research execution and paper trading. Also re-exports
the pre-existing lightweight validation helpers (`legacy`) so historical imports
(`from mentisrex.research.validation import evaluate, train_test, ...`) keep working —
this package is additive over that module, not a replacement.
"""

from mentisrex.research.validation.cross_validation import (
    purged_kfold,
    walk_forward_purged,
)
from mentisrex.research.validation.engine import ResearchValidator, ValidationConfig
from mentisrex.research.validation.hac import (
    hac_significance,
    hac_standard_error,
)

# ── backward-compatible re-exports of the former research/validation.py module ──
from mentisrex.research.validation.legacy import (
    evaluate,
    parameter_sensitivity,
    rolling_validation,
    run_backtest,
    select_features,
    train_test,
    walk_forward,
)
from mentisrex.research.validation.quality import check
from mentisrex.research.validation.report import ValidationReport

__all__ = [
    "ResearchValidator",
    "ValidationConfig",
    "ValidationReport",
    "check",
    # legacy
    "evaluate",
    "hac_significance",
    "hac_standard_error",
    "parameter_sensitivity",
    "purged_kfold",
    "rolling_validation",
    "run_backtest",
    "select_features",
    "train_test",
    "walk_forward",
    "walk_forward_purged",
]

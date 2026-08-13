"""Hypothesis Generation Framework — public API."""

from mentisrex.hypothesis.deduplication import DuplicateResult, DuplicateStatus, check_duplicates
from mentisrex.hypothesis.generator import LLMClient, generate
from mentisrex.hypothesis.models import HypothesisRecord
from mentisrex.hypothesis.quality import QualityResult, check_quality
from mentisrex.hypothesis.store import HypothesisStore

__all__ = [
    "DuplicateResult",
    "DuplicateStatus",
    "HypothesisRecord",
    "HypothesisStore",
    "LLMClient",
    "QualityResult",
    "check_duplicates",
    "check_quality",
    "generate",
]

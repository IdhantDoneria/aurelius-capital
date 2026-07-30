"""Hypothesis Generation Framework — public API."""

from aurelius.hypothesis.deduplication import DuplicateResult, DuplicateStatus, check_duplicates
from aurelius.hypothesis.generator import LLMClient, generate
from aurelius.hypothesis.models import HypothesisRecord
from aurelius.hypothesis.quality import QualityResult, check_quality
from aurelius.hypothesis.store import HypothesisStore

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

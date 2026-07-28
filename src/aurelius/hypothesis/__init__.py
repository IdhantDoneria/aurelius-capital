"""Hypothesis Generation Framework — public API."""
from aurelius.hypothesis.deduplication import DuplicateResult, DuplicateStatus, check_duplicates
from aurelius.hypothesis.generator import LLMClient, generate
from aurelius.hypothesis.models import HypothesisRecord
from aurelius.hypothesis.quality import QualityResult, check_quality
from aurelius.hypothesis.store import HypothesisStore

__all__ = [
    "HypothesisRecord",
    "HypothesisStore",
    "LLMClient",
    "QualityResult",
    "DuplicateResult",
    "DuplicateStatus",
    "generate",
    "check_quality",
    "check_duplicates",
]

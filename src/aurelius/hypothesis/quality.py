"""Quality filter for generated hypotheses.

Eight checks applied in sequence. All checks run; reasons accumulate.
Returns QualityResult(passed, reasons). Caller decides whether to reject.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from aurelius.hypothesis.models import HypothesisRecord

_STOPWORDS = frozenset(
    "the a an of to in and or for is are we our this that with on by as at from be "
    "these those it its their they can using use based over under into than then "
    "which has have had not but also more most any all each per across among between "
    "if when then among over across within".split()
)

_MIN_STATEMENT_LEN = 20
_MIN_INTUITION_LEN = 10
_MIN_UNIQUE_CONTENT_TOKENS = 3
_MIN_CONFIDENCE = 0.1


@dataclass
class QualityResult:
    passed: bool
    reasons: list[str] = field(default_factory=list)


def check_quality(h: HypothesisRecord) -> QualityResult:
    """Run all quality checks. Returns QualityResult with accumulated reasons."""
    reasons: list[str] = []

    if len(h.testable_statement.strip()) < _MIN_STATEMENT_LEN:
        reasons.append("statement_too_short")

    stmt_lower = h.testable_statement.lower()
    if "if " not in stmt_lower and "when " not in stmt_lower:
        reasons.append("not_testable_no_conditional")

    if len(h.economic_intuition.strip()) < _MIN_INTUITION_LEN:
        reasons.append("intuition_missing")

    if not h.required_datasets:
        reasons.append("missing_required_data")

    if not h.asset_classes:
        reasons.append("asset_class_unspecified")

    if h.confidence_score < _MIN_CONFIDENCE:
        reasons.append("confidence_too_low")

    # Vagueness: require at least 3 unique non-stopword tokens in statement
    content_tokens = {
        w for w in h.testable_statement.lower().split()
        if w.isalpha() and w not in _STOPWORDS
    }
    if len(content_tokens) < _MIN_UNIQUE_CONTENT_TOKENS:
        reasons.append("too_vague")

    # Circular reasoning: statement is contained within intuition (near-verbatim)
    if (
        len(h.testable_statement) > 10
        and h.testable_statement.lower().strip() in h.economic_intuition.lower()
    ):
        reasons.append("circular_reasoning")

    return QualityResult(passed=not reasons, reasons=reasons)

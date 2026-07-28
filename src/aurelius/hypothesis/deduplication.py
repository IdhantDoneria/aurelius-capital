"""Duplicate detection for hypotheses.

Three tiers based on Jaccard similarity of testable_statement word sets.
No ML dependencies. Fast enough for 10k hypotheses.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from aurelius.hypothesis._utils import STOPWORDS as _STOPWORDS
from aurelius.hypothesis.models import HypothesisRecord

_EXACT_THRESHOLD = 1.0
_NEAR_DUP_THRESHOLD = 0.70
_VARIATION_THRESHOLD = 0.40


class DuplicateStatus(StrEnum):
    UNIQUE = "unique"
    VARIATION = "variation"          # 0.40–0.69: note it, allow insert
    NEAR_DUPLICATE = "near_duplicate"  # 0.70–0.99: flag for human review
    DUPLICATE = "duplicate"          # 1.0: block insert


@dataclass
class DuplicateResult:
    status: DuplicateStatus
    similar_ids: list[str]           # IDs of similar/duplicate hypotheses
    max_similarity: float


def check_duplicates(
    hypothesis: HypothesisRecord,
    existing_statements: list[tuple[str, str]],  # (hypothesis_id, testable_statement)
) -> DuplicateResult:
    """Compare hypothesis against all existing statements.

    existing_statements: list of (id, testable_statement) from HypothesisStore.all_statements().
    """
    stmt = hypothesis.testable_statement

    near_dups: list[tuple[float, str]] = []

    for hyp_id, other_stmt in existing_statements:
        if hyp_id == hypothesis.id:
            continue
        sim = _jaccard(stmt, other_stmt)
        if sim >= _VARIATION_THRESHOLD:
            near_dups.append((sim, hyp_id))

    if not near_dups:
        return DuplicateResult(DuplicateStatus.UNIQUE, [], 0.0)

    near_dups.sort(reverse=True)
    max_sim, _ = near_dups[0]
    similar_ids = [hyp_id for _, hyp_id in near_dups]

    if max_sim >= _EXACT_THRESHOLD:
        return DuplicateResult(DuplicateStatus.DUPLICATE, similar_ids, max_sim)
    if max_sim >= _NEAR_DUP_THRESHOLD:
        return DuplicateResult(DuplicateStatus.NEAR_DUPLICATE, similar_ids, max_sim)
    return DuplicateResult(DuplicateStatus.VARIATION, similar_ids, max_sim)


def _jaccard(a: str, b: str) -> float:
    wa = _tokens(a)
    wb = _tokens(b)
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


def _tokens(text: str) -> set[str]:
    return {w for w in text.lower().split() if w.isalpha() and w not in _STOPWORDS}

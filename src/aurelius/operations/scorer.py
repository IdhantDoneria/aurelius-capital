"""Rule-based priority scorer for research papers.

Produces a 0-10 score. Higher = higher priority for experiment generation.
No LLM required — all factors derivable from extracted metadata.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from aurelius.operations.models import PaperScore


# Weights sum to 1.0
_WEIGHTS = {
    "novelty": 0.20,
    "influence": 0.15,
    "reproducibility": 0.20,
    "dataset_availability": 0.20,
    "expected_value": 0.15,
    "engineering_effort": 0.10,  # inverted: low effort = high score
}


def score_paper(paper_id: str, meta: dict[str, Any]) -> PaperScore:
    """Score a paper on 6 factors, return PaperScore with total 0-10."""
    novelty = _novelty(meta)
    influence = _influence(meta)
    reproducibility = _reproducibility(meta)
    dataset_avail = _dataset_availability(meta)
    expected_value = _expected_value(meta)
    engineering_effort = _engineering_effort(meta)  # 0-10, lower = easier

    # engineering effort inverted for weighted sum (easy = more desirable)
    effort_score = (10.0 - engineering_effort) / 10.0

    total = 10.0 * (
        _WEIGHTS["novelty"] * novelty
        + _WEIGHTS["influence"] * influence
        + _WEIGHTS["reproducibility"] * reproducibility
        + _WEIGHTS["dataset_availability"] * dataset_avail
        + _WEIGHTS["expected_value"] * expected_value
        + _WEIGHTS["engineering_effort"] * effort_score
    )

    rationale = (
        f"novelty={novelty:.2f} influence={influence:.2f} "
        f"reproducibility={reproducibility:.2f} dataset_avail={dataset_avail:.2f} "
        f"expected_value={expected_value:.2f} effort={engineering_effort:.2f}"
    )

    return PaperScore(
        paper_id=paper_id,
        novelty=novelty,
        influence=influence,
        reproducibility=reproducibility,
        dataset_availability=dataset_avail,
        expected_value=expected_value,
        engineering_effort=engineering_effort,
        total=round(total, 2),
        rationale=rationale,
    )


# ── individual factor functions (return 0.0 - 1.0) ──────────────────────────

def _novelty(meta: dict) -> float:
    """Newer papers = more novel. Bonus for arXiv preprints."""
    year = meta.get("year")
    if not year:
        return 0.3
    current_year = datetime.now(UTC).year
    age = current_year - int(year)
    base = max(0.0, 1.0 - age / 10.0)  # 0-10 years old → 1.0-0.0
    bonus = 0.1 if meta.get("arxiv_id") else 0.0
    return min(1.0, base + bonus)


def _influence(meta: dict) -> float:
    """Proxy: reference count and methodology sophistication."""
    ref_count = meta.get("reference_count", 0)
    stat_tests = len(meta.get("statistical_tests", []))
    ref_score = min(1.0, ref_count / 50.0)
    stat_score = min(1.0, stat_tests / 5.0)
    return 0.6 * ref_score + 0.4 * stat_score


def _reproducibility(meta: dict) -> float:
    """Has methodology, datasets, and statistical results described."""
    score = 0.0
    if meta.get("methodology"):
        score += 0.35
    if meta.get("datasets_mentioned"):
        score += 0.35
    if meta.get("statistical_tests"):
        score += 0.20
    if meta.get("results"):
        score += 0.10
    return min(1.0, score)


def _dataset_availability(meta: dict) -> float:
    """How many mentioned datasets are commonly available."""
    # Known open/widely-available datasets
    _available = {
        "Ken French", "Fama-French", "CRSP", "Yahoo Finance", "S&P 500",
        "Russell", "MSCI", "Quandl",
    }
    mentioned = set(meta.get("datasets_mentioned", []))
    if not mentioned:
        return 0.3  # unknown → assume moderate
    available_count = len(mentioned & _available)
    return min(1.0, available_count / max(1, len(mentioned)))


def _expected_value(meta: dict) -> float:
    """Abstract + features + results present = higher expected value."""
    score = 0.0
    if meta.get("abstract") and len(meta["abstract"]) > 100:
        score += 0.4
    features = meta.get("features_mentioned", [])
    if features:
        score += min(0.4, len(features) / 10.0)
    if meta.get("results"):
        score += 0.2
    return min(1.0, score)


def _engineering_effort(meta: dict) -> float:
    """Estimate implementation complexity 0-10 (lower = easier)."""
    effort = 3.0  # baseline
    features = len(meta.get("features_mentioned", []))
    datasets = len(meta.get("datasets_mentioned", []))
    effort += min(3.0, features / 5.0)
    effort += min(2.0, datasets / 3.0)
    # Complex methodology = more effort
    method = meta.get("methodology", "")
    for keyword in ("neural", "deep learning", "reinforcement", "NLP", "alternative data"):
        if keyword.lower() in method.lower():
            effort += 1.0
    return min(10.0, effort)

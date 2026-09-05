"""Generate experiment specifications from extracted paper metadata.

Produces an ExperimentSpec that the pipeline queues for execution.
Rule-based — no LLM required; LLM injection available for richer specs.
"""

from __future__ import annotations

import re
from typing import Any

from mentisrex.operations.models import ExperimentSpec

# Known available datasets in the platform
_PLATFORM_DATASETS = {
    "yahoo_finance",
    "ken_french",
    "fama_french",
    "sp500",
    "russell",
    "msci",
    "crsp",
    "quandl",
}

_DATASET_NORMALIZE = {
    "Yahoo Finance": "yahoo_finance",
    "Ken French": "ken_french",
    "Fama-French": "fama_french",
    "S&P 500": "sp500",
    "Russell": "russell",
    "MSCI": "msci",
    "CRSP": "crsp",
    "Quandl": "quandl",
    "Bloomberg": "bloomberg",
    "FactSet": "factset",
    "Compustat": "compustat",
    "WRDS": "wrds",
    "Refinitiv": "refinitiv",
}


def plan_experiment(paper_id: str, meta: dict[str, Any], priority_score: float) -> ExperimentSpec:
    """Derive a minimal ExperimentSpec from paper metadata."""
    title = meta.get("title", "Unknown Paper")
    strategy_name = _derive_strategy_name(title, meta)
    hypothesis = _derive_hypothesis(meta)
    required_datasets = _normalize_datasets(meta.get("datasets_mentioned", []))
    required_features = meta.get("features_mentioned", [])[:10]
    methodology = meta.get("methodology", "")[:500]
    missing = [d for d in required_datasets if d not in _PLATFORM_DATASETS]

    checklist = [
        "Paper methodology section reviewed",
        f"Required datasets confirmed: {required_datasets or ['unknown']}",
        "Feature engineering pipeline validated",
        "Backtest date range selected (avoid look-ahead bias)",
        "IS/OOS split defined",
        "Statistical significance threshold set (p < 0.05)",
        "Transaction costs and slippage parameterized",
        "Benchmark selected for comparison",
    ]

    return ExperimentSpec(
        paper_id=paper_id,
        title=title,
        strategy_name=strategy_name,
        hypothesis_statement=hypothesis,
        required_datasets=required_datasets,
        required_features=required_features,
        methodology=methodology,
        params={
            "lookback": 20,
            "rebalance_freq": "monthly",
            "universe": "sp500",
        },
        expected_metrics=["sharpe_ratio", "max_drawdown", "oos_return", "t_stat"],
        reproducibility_checklist=checklist,
        missing_prerequisites=missing,
        ready_to_run=len(missing) == 0,
        priority_score=priority_score,
    )


def _normalize_datasets(mentioned: list[str]) -> list[str]:
    """Map human-readable dataset names to platform-normalized IDs."""
    return [
        _DATASET_NORMALIZE.get(d, d.lower().replace(" ", "_").replace("-", "_")) for d in mentioned
    ]


def _derive_strategy_name(title: str, meta: dict) -> str:
    """Slugify the paper title into a strategy name."""
    # Remove common stop words and punctuation
    clean = re.sub(r"[^\w\s]", "", title.lower())
    words = [
        w
        for w in clean.split()
        if w
        not in {
            "a",
            "an",
            "the",
            "in",
            "on",
            "of",
            "and",
            "or",
            "for",
            "to",
            "with",
            "from",
            "evidence",
            "study",
            "analysis",
        }
    ]
    slug = "_".join(words[:5])
    return slug or "paper_strategy"


def _derive_hypothesis(meta: dict) -> str:
    """Construct a testable hypothesis statement from paper content."""
    abstract = meta.get("abstract", "")
    features = meta.get("features_mentioned", [])
    meta.get("datasets_mentioned", [])

    if abstract and len(abstract) > 80:
        # Take first 2 sentences of abstract as the hypothesis basis
        sentences = re.split(r"(?<=[.!?])\s+", abstract)
        basis = " ".join(sentences[:2])[:300]
        return f"Hypothesis derived from paper abstract: {basis}"

    if features:
        return (
            f"Factor strategy based on {', '.join(features[:3])} "
            f"generates statistically significant risk-adjusted returns."
        )

    return f"Paper strategy (ID: {meta.get('arxiv_id', 'unknown')}) generates alpha."

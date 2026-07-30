"""LLM-based field extraction from paper abstracts.

LLMClient is injected — same pattern as aurelius.assistant. Works offline
(returns Paper unchanged) when no LLM is supplied.
"""

from __future__ import annotations

import json
from collections.abc import Callable

from aurelius.literature.models import Paper

LLMClient = Callable[[str], str]

_PROMPT = """\
Extract structured metadata from this quantitative finance research paper.

Title: {title}
Authors: {authors}
Abstract: {abstract}

Return valid JSON with exactly these keys:
- keywords: list[str] — 3-8 domain keywords
- asset_classes: list[str] — subset of [equities, fixed_income, fx, commodities, crypto, multi_asset, derivatives, real_estate, alternatives]  # noqa: E501
- research_category: str — one of [factor_anomaly, market_microstructure, macro, portfolio_construction, risk, ml_ai, high_frequency, derivatives, esg, alternative_data, other]  # noqa: E501
- methodology: str — one of [empirical, theoretical, simulation, survey, meta_analysis]
- datasets: list[str] — dataset or data source names mentioned
- factors_studied: list[str] — factor names (e.g. value, momentum, quality, low_volatility)
- statistical_techniques: list[str] — statistical or ML methods used
- main_conclusions: str — 2-3 sentence summary of main findings
- limitations: str — key limitations or caveats mentioned

Respond with JSON only."""


def enrich(paper: Paper, llm: LLMClient) -> Paper:
    """Call LLM to fill enrichment fields. Mutates paper in-place, returns it."""
    prompt = _PROMPT.format(
        title=paper.title,
        authors=", ".join(paper.authors[:5]),
        abstract=paper.abstract or "(no abstract available)",
    )
    raw = llm(prompt)
    try:
        data = json.loads(_extract_json(raw))
    except (json.JSONDecodeError, ValueError):
        return paper

    paper.keywords = _str_list(data.get("keywords"))
    paper.asset_classes = _str_list(data.get("asset_classes"))
    paper.research_category = str(data.get("research_category") or "")
    paper.methodology = str(data.get("methodology") or "")
    paper.datasets = _str_list(data.get("datasets"))
    paper.factors_studied = _str_list(data.get("factors_studied"))
    paper.statistical_techniques = _str_list(data.get("statistical_techniques"))
    paper.main_conclusions = str(data.get("main_conclusions") or "")
    paper.limitations = str(data.get("limitations") or "")
    paper.enriched = True
    return paper


def _extract_json(text: str) -> str:
    _decoder = json.JSONDecoder()
    for _i, _ch in enumerate(text):
        if _ch == "{":
            try:
                _, _end = _decoder.raw_decode(text, _i)
                return text[_i:_end]
            except json.JSONDecodeError:
                continue
    return text


def _str_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(v) for v in value]
    if isinstance(value, str):
        return [value] if value else []
    return []

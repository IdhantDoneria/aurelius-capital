"""HypothesisGenerator — converts enriched Papers into HypothesisRecords.

LLMClient is injected (same seam as literature.enrichment and assistant).
Offline fallback: template-based generation from factors x asset_classes.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from mentisrex.hypothesis.models import HypothesisRecord
from mentisrex.literature.models import Paper

LLMClient = Callable[[str], str]

_PROMPT = """\
You are a systematic quantitative research analyst. Given the following paper summary, \
generate 1 to 3 distinct, testable quantitative trading hypotheses.

Paper title: {title}
Authors: {authors}
Research category: {research_category}
Methodology: {methodology}
Factors studied: {factors}
Asset classes: {asset_classes}
Datasets used: {datasets}
Main conclusions: {conclusions}
Known limitations: {limitations}

For each hypothesis return a JSON object with exactly these keys:
- economic_intuition: string (1-2 sentences explaining WHY this should generate returns)
- testable_statement: string (must contain IF or WHEN: "IF [measurable condition] THEN [expected outcome] AMONG [universe] OVER [horizon]")  # noqa: E501
- expected_behavior: string (what pattern to observe in the data)
- asset_classes: list[string]
- required_datasets: list[string] (specific data sources needed)
- required_features: list[string] (computed signals or features)
- holding_period: string (e.g. "1_month", "1_week", "1_day", "3_months")
- expected_risks: list[string] (crowding, factor timing, macro sensitivity, etc.)
- confidence_score: float between 0.0 and 1.0
- assumptions: list[string]
- dependencies: list[string] (other factors or conditions required)
- validation_requirements: list[string] (what is needed to confirm this works)

Return a JSON array (even for a single hypothesis). JSON only, no prose."""


def generate(
    paper: Paper,
    llm: LLMClient | None = None,
    researcher: str = "llm",
) -> list[HypothesisRecord]:
    """Generate hypotheses from a paper. Uses LLM if provided, else template fallback."""
    if llm is not None:
        records = _generate_llm(paper, llm, researcher)
        if records:
            return records
    # LLM absent or returned nothing parseable → template fallback
    return _generate_template(paper, researcher)


def _generate_llm(paper: Paper, llm: LLMClient, researcher: str) -> list[HypothesisRecord]:
    prompt = _PROMPT.format(
        title=paper.title,
        authors=", ".join(paper.authors[:5]),
        research_category=paper.research_category or "unknown",
        methodology=paper.methodology or "unknown",
        factors=", ".join(paper.factors_studied) or "unspecified",
        asset_classes=", ".join(paper.asset_classes) or "unspecified",
        datasets=", ".join(paper.datasets) or "unspecified",
        conclusions=paper.main_conclusions or paper.abstract[:500],
        limitations=paper.limitations or "none stated",
    )

    raw = llm(prompt)
    try:
        items = json.loads(_extract_json_array(raw))
        if not isinstance(items, list):
            items = [items]
    except (json.JSONDecodeError, ValueError):
        return []

    now = datetime.now(UTC)
    records = []
    for item in items[:3]:  # cap at 3 per paper
        if not isinstance(item, dict):
            continue
        try:
            records.append(_dict_to_record(item, paper, now, researcher, "llm"))
        except (KeyError, TypeError):
            continue
    return records


def _generate_template(paper: Paper, researcher: str) -> list[HypothesisRecord]:
    """Minimal offline generator: one hypothesis per (factor, asset_class) pair."""
    now = datetime.now(UTC)
    records = []

    factors = paper.factors_studied or ["unknown_factor"]
    asset_classes = paper.asset_classes or ["equities"]

    for factor in factors[:2]:  # limit combinatorial explosion
        for asset_class in asset_classes[:2]:
            stmt = (
                f"IF {factor} signal is in top decile "
                f"THEN next-month returns are positive AMONG {asset_class} OVER 1_month"
            )
            intuition = (
                f"Based on {paper.title}, {factor} shows predictive power in "
                f"{asset_class}. The evidence suggests a systematic premium exists."
            )
            records.append(
                HypothesisRecord(
                    id=str(uuid.uuid4()),
                    parent_papers=[paper.id],
                    research_category=paper.research_category or "other",
                    economic_intuition=intuition,
                    testable_statement=stmt,
                    expected_behavior=f"Top-decile {factor} portfolio outperforms bottom decile.",
                    asset_classes=[asset_class],
                    required_datasets=paper.datasets or ["price_data"],
                    required_features=[factor],
                    holding_period="1_month",
                    expected_risks=["factor_crowding", "data_mining"],
                    confidence_score=0.3,  # low confidence for template-generated
                    assumptions=[
                        f"{factor} can be computed from available data",
                        "Signal is available before return period",
                    ],
                    dependencies=[],
                    validation_requirements=[
                        "OOS Sharpe > 0.5",
                        "Positive after transaction costs",
                        "Stable across sub-periods",
                    ],
                    status="Draft",
                    version=1,
                    created_at=now,
                    updated_at=now,
                    researcher=researcher,
                    generation_method="template",
                )
            )

    return records


def _dict_to_record(
    d: dict,
    paper: Paper,
    now: datetime,
    researcher: str,
    method: str,
) -> HypothesisRecord:
    return HypothesisRecord(
        id=str(uuid.uuid4()),
        parent_papers=[paper.id],
        research_category=str(d.get("research_category") or paper.research_category or "other"),
        economic_intuition=str(d.get("economic_intuition", "")),
        testable_statement=str(d.get("testable_statement", "")),
        expected_behavior=str(d.get("expected_behavior", "")),
        asset_classes=_str_list(d.get("asset_classes")),
        required_datasets=_str_list(d.get("required_datasets")),
        required_features=_str_list(d.get("required_features")),
        holding_period=str(d.get("holding_period") or "unknown"),
        expected_risks=_str_list(d.get("expected_risks")),
        confidence_score=float(d.get("confidence_score") or 0.0),
        assumptions=_str_list(d.get("assumptions")),
        dependencies=_str_list(d.get("dependencies")),
        validation_requirements=_str_list(d.get("validation_requirements")),
        status="Draft",
        version=1,
        created_at=now,
        updated_at=now,
        researcher=researcher,
        generation_method=method,
    )


def _extract_json_array(text: str) -> str:
    """Extract first [...] or {...} block from LLM output."""
    _decoder = json.JSONDecoder()
    for _i, _ch in enumerate(text):
        if _ch in ("[", "{"):
            try:
                _obj, _ = _decoder.raw_decode(text, _i)
                if isinstance(_obj, list):
                    return json.dumps(_obj)
                return json.dumps([_obj])
            except json.JSONDecodeError:
                continue
    return "[]"


def _str_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(v) for v in value]
    if isinstance(value, str):
        return [value] if value else []
    return []

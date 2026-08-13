"""ValidationReport + verdict engine (AIDP M9).

The verdict references concrete diagnostics (numbers, not slogans). Four outcomes:
PASS, PASS_WITH_WARNINGS, REJECT, REQUIRES_REVIEW. A deterministic manifest hash
makes the report content-addressable.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, field


@dataclass
class ValidationReport:
    overall_verdict: str
    confidence_score: float
    deployment_recommendation: str
    warnings: list[str] = field(default_factory=list)
    critical_failures: list[str] = field(default_factory=list)
    statistical_summary: dict = field(default_factory=dict)
    robustness_summary: dict = field(default_factory=dict)
    capacity_summary: dict = field(default_factory=dict)
    risk_summary: dict = field(default_factory=dict)
    overfitting_summary: dict = field(default_factory=dict)
    visualizations: dict = field(default_factory=dict)
    execution_metadata: dict = field(default_factory=dict)
    # scoring / provenance
    research_score: float = 0.0
    component_scores: dict = field(default_factory=dict)
    score_contributions: dict = field(default_factory=dict)
    diagnostics: list[dict] = field(default_factory=list)
    reasoning: list[str] = field(default_factory=list)
    validation_version: str = "1.0.0"
    manifest_hash: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("visualizations", None)      # heavy series live in a separate artifact
        return d


VERDICTS = ("PASS", "PASS_WITH_WARNINGS", "REJECT", "REQUIRES_REVIEW")


def decide(score_result: dict, flags: list, summaries: dict, *,
           review_threshold: float = 50.0, p_threshold: float = 0.05) -> dict:
    critical = [f for f in flags if f.severity == "critical"]
    warnings = [f for f in flags if f.severity == "warning"]
    sig = summaries.get("significance", {})
    p = sig.get("p_value", 1.0)
    sr = sig.get("sharpe", 0.0)
    dsr = summaries.get("overfitting", {}).get("dsr")
    rs = score_result["research_score"]

    hard: list[str] = []
    if sr <= 0:
        hard.append(f"annualized Sharpe {sr:.2f} ≤ 0 — no edge")
    if p > p_threshold:
        hard.append(f"p-value {p:.3f} > {p_threshold} — not statistically significant")
    if dsr is not None and not math.isnan(dsr) and dsr < 0.5:
        hard.append(f"Deflated Sharpe {dsr:.2f} < 0.5 — likely overfit")
    hard += [f.detail for f in critical]

    warn_msgs = [f.detail for f in warnings]

    # only CORE analyses (computable from returns alone) count toward "inconclusive";
    # absent optional enrichment (benchmark/positions/evaluator) does not force review.
    missing = _core_missing(summaries)

    if hard:
        return _verdict("REJECT", rs, hard, warn_msgs,
                        "Do not deploy — reproduce or redesign.", summaries)
    if missing >= 2 or rs < review_threshold:
        reason = [f"research score {rs:.0f} < {review_threshold:.0f}"] if rs < review_threshold else []
        reason += [f"{missing} core analyses could not be computed"] if missing >= 2 else []
        return _verdict("REQUIRES_REVIEW", rs, [], warn_msgs,
                        "Manual review required before deployment.", summaries, reason)
    if warn_msgs:
        return _verdict("PASS_WITH_WARNINGS", rs, [], warn_msgs,
                        "Deploy to paper trading with monitoring on the flagged risks.", summaries)
    return _verdict("PASS", rs, [], [], "Approved for paper trading.", summaries,
                    [f"Sharpe {sr:.2f}, p={p:.3f}, research score {rs:.0f}/100 — all gates passed"])


def _verdict(verdict, rs, critical, warnings, rec, summaries, reasoning=None):
    return {"verdict": verdict, "confidence_score": rs, "critical_failures": critical,
            "warnings": warnings, "deployment_recommendation": rec,
            "reasoning": reasoning or (critical + warnings)}


def _core_missing(summaries: dict) -> int:
    """Count core analyses (always computable from the return series) that failed —
    the only 'inconclusive' signal that should trigger review."""
    n = 0
    if not summaries.get("bootstrap", {}).get("n_samples"):
        n += 1
    if not summaries.get("monte_carlo", {}).get("n_samples"):
        n += 1
    dsr = summaries.get("overfitting", {}).get("dsr")
    if dsr is None or (isinstance(dsr, float) and math.isnan(dsr)):
        n += 1
    if summaries.get("robustness", {}).get("rolling", {}).get("folds", 0) == 0:
        n += 1
    return n


def manifest_hash(report: ValidationReport) -> str:
    core = {"verdict": report.overall_verdict, "score": round(report.confidence_score, 4),
            "components": {k: round(v, 4) for k, v in report.component_scores.items()},
            "version": report.validation_version}
    return hashlib.blake2b(json.dumps(core, sort_keys=True).encode(), digest_size=16).hexdigest()

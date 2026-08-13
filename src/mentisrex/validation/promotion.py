"""Promotion decision engine — classify every experiment into one of 5 states.

States (ordered by confidence):
  REJECTED                 — failed fundamental checks; do not revisit without new data
  REQUIRES_MORE_RESEARCH   — inconclusive; extend data, refine hypothesis, retry
  ARCHIVED                 — works in narrow conditions only; document, do not promote
  APPROVED_FOR_FURTHER_VALIDATION — marginal pass; needs more robustness testing before paper
  APPROVED_FOR_PAPER_TRADING      — passes all checks; ready for live paper trading

Decisions are evidence-based: every state includes the specific checks that drove it.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass


class PromotionState(enum.StrEnum):
    REJECTED = "rejected"
    REQUIRES_MORE_RESEARCH = "requires_more_research"
    ARCHIVED = "archived"
    APPROVED_FOR_FURTHER_VALIDATION = "approved_for_further_validation"
    APPROVED_FOR_PAPER_TRADING = "approved_for_paper_trading"


@dataclass
class PromotionDecision:
    state: PromotionState
    evidence: list[str]  # reasons for the decision (pro and con)
    blocking_issues: list[str]  # issues that prevented a higher state
    confidence_score: float  # 0.0 - 1.0 composite score
    next_steps: list[str]  # actionable recommendations


@dataclass(frozen=True)
class PromotionCriteria:
    """Calibration knobs. Defaults are conservative institutional thresholds."""

    # Hard gates for APPROVED_FOR_PAPER_TRADING
    min_sharpe_paper: float = 0.5
    max_adj_pvalue_paper: float = 0.05
    min_tc_breakeven_bps: float = 30.0
    must_be_wf_consistent: bool = True

    # Relaxed gates for APPROVED_FOR_FURTHER_VALIDATION
    min_sharpe_further: float = 0.3
    max_adj_pvalue_further: float = 0.10

    # Gates for REQUIRES_MORE_RESEARCH vs REJECTED
    min_oos_observations: int = 30
    absolute_reject_sharpe: float = -0.5  # below this → always REJECTED

    # Regime: must be positive in this fraction of detected regimes
    min_positive_regime_fraction: float = 0.5


class PromotionEngine:
    def __init__(self, criteria: PromotionCriteria | None = None) -> None:
        self._c = criteria or PromotionCriteria()

    def decide(
        self,
        *,
        oos_sharpe: float,
        is_sharpe: float,
        adj_pvalue: float,
        n_oos_observations: int,
        tc_breakeven_bps: float,
        wf_consistent: bool,
        regime_consistent: bool,
        param_cv: float | None,
        wf_sharpes: list[float],
        is_robust: bool,
        existing_verdict: str = "",
    ) -> PromotionDecision:
        c = self._c
        evidence: list[str] = []
        blocking: list[str] = []

        # ── evidence collection ───────────────────────────────────────────────
        evidence.append(f"OOS Sharpe: {oos_sharpe:.3f}")
        evidence.append(f"IS Sharpe: {is_sharpe:.3f}")
        evidence.append(f"adj p-value: {adj_pvalue:.4f}")
        evidence.append(f"OOS observations: {n_oos_observations}")
        evidence.append(f"TC breakeven: {tc_breakeven_bps:.0f} bps")
        evidence.append(f"walk-forward consistent: {wf_consistent}")
        evidence.append(f"regime consistent: {regime_consistent}")
        if param_cv is not None:
            evidence.append(f"parameter CV: {param_cv:.3f}")
        if wf_sharpes:
            evidence.append(f"WF folds: {[round(s, 2) for s in wf_sharpes]}")

        # ── confidence score ──────────────────────────────────────────────────
        score = 0.5
        score += min(0.15, oos_sharpe * 0.15)  # +0.15 for Sharpe=1.0
        if adj_pvalue <= 0.05:
            score += 0.10
        elif adj_pvalue <= 0.10:
            score += 0.05
        if wf_consistent:
            score += 0.10
        if regime_consistent:
            score += 0.05
        if tc_breakeven_bps >= 50:
            score += 0.10
        elif tc_breakeven_bps >= 30:
            score += 0.05
        if param_cv is not None and param_cv < 0.3:
            score += 0.05
        if is_robust:
            score += 0.05
        # Deductions
        if oos_sharpe < 0:
            score -= 0.20
        if adj_pvalue > 0.10:
            score -= 0.10
        if not wf_consistent:
            score -= 0.10
        if not regime_consistent:
            score -= 0.05
        score = max(0.0, min(1.0, score))

        # ── decision tree ─────────────────────────────────────────────────────

        # Insufficient data — inconclusive, not a verdict
        if n_oos_observations < c.min_oos_observations:
            blocking.append(
                f"insufficient OOS data ({n_oos_observations} < {c.min_oos_observations} obs)"
            )
            return PromotionDecision(
                state=PromotionState.REQUIRES_MORE_RESEARCH,
                evidence=evidence,
                blocking_issues=blocking,
                confidence_score=score,
                next_steps=[
                    "extend backtest period to accumulate ≥30 OOS observations",
                    "consider lower-frequency data if daily bars are limited",
                ],
            )

        # Hard reject
        if oos_sharpe <= c.absolute_reject_sharpe:
            blocking.append(
                f"OOS Sharpe {oos_sharpe:.3f} below absolute floor {c.absolute_reject_sharpe}"
            )
            return PromotionDecision(
                state=PromotionState.REJECTED,
                evidence=evidence,
                blocking_issues=blocking,
                confidence_score=score,
                next_steps=[
                    "revisit hypothesis — the edge assumed does not exist in this data",
                    "check for implementation errors before concluding the hypothesis is wrong",
                ],
            )

        # Check APPROVED_FOR_PAPER_TRADING gates
        paper_gates = {
            "sharpe_floor": oos_sharpe >= c.min_sharpe_paper,
            "significance": adj_pvalue <= c.max_adj_pvalue_paper,
            "tc_robust": tc_breakeven_bps >= c.min_tc_breakeven_bps,
            "wf_consistent": wf_consistent or not c.must_be_wf_consistent,
        }
        paper_pass = all(paper_gates.values())

        # Check APPROVED_FOR_FURTHER_VALIDATION gates
        further_gates = {
            "sharpe_floor": oos_sharpe >= c.min_sharpe_further,
            "significance": adj_pvalue <= c.max_adj_pvalue_further,
        }
        further_pass = all(further_gates.values())

        if paper_pass:
            return PromotionDecision(
                state=PromotionState.APPROVED_FOR_PAPER_TRADING,
                evidence=evidence,
                blocking_issues=[],
                confidence_score=score,
                next_steps=[
                    "allocate a paper trading account and begin live monitoring",
                    "set IS Sharpe as the benchmark; flag if live Sharpe drops below 50% of IS",
                    "monitor capacity utilization against estimated ADV limits",
                    f"set drawdown halt at {abs(min(oos_sharpe, 0.5) * 0.5):.0%} live equity loss",
                ],
            )

        # Identify what's blocking paper trading
        for gate, passed in paper_gates.items():
            if not passed:
                blocking.append(f"failed gate: {gate}")

        if further_pass:
            # Check if it's regime-specific (archive vs further validation)
            if not regime_consistent and not wf_consistent:
                return PromotionDecision(
                    state=PromotionState.ARCHIVED,
                    evidence=evidence,
                    blocking_issues=blocking,
                    confidence_score=score,
                    next_steps=[
                        "document regime conditions where strategy works",
                        "revisit if a regime classifier can be added as a filter",
                        "consider this as one component of a multi-regime ensemble",
                    ],
                )
            return PromotionDecision(
                state=PromotionState.APPROVED_FOR_FURTHER_VALIDATION,
                evidence=evidence,
                blocking_issues=blocking,
                confidence_score=score,
                next_steps=[
                    "run on out-of-universe data (different symbols/dates) to confirm",
                    "investigate blocking issues before committing paper capital",
                    "tighten cost assumptions and re-validate",
                ],
            )

        # Marginal: requires more research if at least directionally right
        if oos_sharpe > 0:
            return PromotionDecision(
                state=PromotionState.REQUIRES_MORE_RESEARCH,
                evidence=evidence,
                blocking_issues=blocking,
                confidence_score=score,
                next_steps=[
                    "extend lookback period for more OOS observations",
                    "refine strategy parameters to reduce parameter sensitivity",
                    "investigate transaction cost sensitivity",
                ],
            )

        # Rejected
        return PromotionDecision(
            state=PromotionState.REJECTED,
            evidence=evidence,
            blocking_issues=blocking,
            confidence_score=score,
            next_steps=[
                "hypothesis rejected — record rationale before discarding",
                "check if edge exists in a sub-universe or specific market regime",
            ],
        )

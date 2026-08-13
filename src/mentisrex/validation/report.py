"""ComprehensiveReport — the complete validation deliverable.

One report per experiment. Contains everything needed to:
  - Understand the result
  - Reproduce the calculation
  - Defend the promotion decision
  - Audit inputs and environment

to_dict()     → JSON-serializable dict for storage
to_markdown() → human-readable report for review meetings
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime

from mentisrex.validation.audit import AuditRecord
from mentisrex.validation.metrics import ExtendedMetrics
from mentisrex.validation.promotion import PromotionDecision
from mentisrex.validation.robustness import RobustnessAssessment
from mentisrex.validation.stats import BootstrapResult, PermutationResult


@dataclass
class ComprehensiveReport:
    # ── identity ──────────────────────────────────────────────────────────────
    experiment_id: str
    hypothesis_id: str
    researcher: str
    validated_at: datetime

    # ── performance ───────────────────────────────────────────────────────────
    metrics: ExtendedMetrics

    # ── statistical evidence ──────────────────────────────────────────────────
    sharpe_bootstrap: BootstrapResult
    permutation: PermutationResult
    bonferroni_adj_pvalue: float
    n_trials: int

    # ── robustness ────────────────────────────────────────────────────────────
    robustness: RobustnessAssessment

    # ── parameter sensitivity ─────────────────────────────────────────────────
    param_cv: float | None  # None if no param grid was provided
    param_sensitivity_metric: str = "sharpe_ratio"

    # ── promotion ─────────────────────────────────────────────────────────────
    promotion: PromotionDecision = field(
        default_factory=lambda: PromotionDecision(
            state=__import__(
                "mentisrex.validation.promotion", fromlist=["PromotionState"]
            ).PromotionState.REJECTED,
            evidence=[],
            blocking_issues=[],
            confidence_score=0.0,
            next_steps=[],
        )
    )

    # ── auditability ──────────────────────────────────────────────────────────
    audit: AuditRecord = field(
        default_factory=lambda: AuditRecord(
            validated_at=datetime.utcnow(),
            python_version="",
            platform="",
            mentisrex_commit="",
            config_hash="",
            dataset_fingerprint="",
            random_seed=0,
        )
    )

    # ── narrative ─────────────────────────────────────────────────────────────
    known_weaknesses: list[str] = field(default_factory=list)
    known_strengths: list[str] = field(default_factory=list)

    # ── convenience ──────────────────────────────────────────────────────────

    @property
    def confidence_score(self) -> float:
        return self.promotion.confidence_score

    def to_dict(self) -> dict:
        def _default(obj):
            if hasattr(obj, "to_dict"):
                return obj.to_dict()
            if hasattr(obj, "__dataclass_fields__"):
                return asdict(obj)
            if hasattr(obj, "value"):  # StrEnum
                return obj.value
            return str(obj)

        return json.loads(
            json.dumps(
                {
                    "experiment_id": self.experiment_id,
                    "hypothesis_id": self.hypothesis_id,
                    "researcher": self.researcher,
                    "validated_at": self.validated_at.isoformat(),
                    "metrics": asdict(self.metrics),
                    "statistical_evidence": {
                        "sharpe_bootstrap_ci_95": {
                            "lower": self.sharpe_bootstrap.ci_lower,
                            "observed": self.sharpe_bootstrap.observed,
                            "upper": self.sharpe_bootstrap.ci_upper,
                            "bias": self.sharpe_bootstrap.bias,
                            "n_samples": self.sharpe_bootstrap.n_samples,
                        },
                        "permutation_pvalue": self.permutation.pvalue,
                        "permutation_n": self.permutation.n_permutations,
                        "bonferroni_adj_pvalue": self.bonferroni_adj_pvalue,
                        "n_trials": self.n_trials,
                    },
                    "robustness": {
                        "is_robust": self.robustness.is_robust,
                        "regime_consistent": self.robustness.regime_consistent,
                        "tc_breakeven_bps": self.robustness.tc_sweep.breakeven,
                        "slippage_breakeven_bps": self.robustness.slippage_sweep.breakeven,
                        "walk_forward_cv": self.robustness.walk_forward_cv,
                        "walk_forward_sharpes": self.robustness.walk_forward_sharpes,
                        "worst_fold_sharpe": self.robustness.worst_fold_sharpe,
                        "regime_stats": [asdict(r) for r in self.robustness.regime_stats],
                        "weaknesses": self.robustness.weaknesses,
                        "strengths": self.robustness.strengths,
                    },
                    "parameter_sensitivity": {
                        "cv": self.param_cv,
                        "metric": self.param_sensitivity_metric,
                    },
                    "promotion": {
                        "state": self.promotion.state.value,
                        "confidence_score": self.promotion.confidence_score,
                        "evidence": self.promotion.evidence,
                        "blocking_issues": self.promotion.blocking_issues,
                        "next_steps": self.promotion.next_steps,
                    },
                    "audit": self.audit.to_dict(),
                    "known_weaknesses": self.known_weaknesses,
                    "known_strengths": self.known_strengths,
                },
                default=_default,
            )
        )

    def to_markdown(self) -> str:
        m = self.metrics
        r = self.robustness
        p = self.promotion
        bs = self.sharpe_bootstrap

        lines: list[str] = [
            f"# Validation Report — {self.experiment_id}",
            "",
            f"**Hypothesis:** `{self.hypothesis_id}`  ",
            f"**Researcher:** {self.researcher}  ",
            f"**Validated:** {self.validated_at.strftime('%Y-%m-%d %H:%M UTC')}  ",
            f"**Commit:** `{self.audit.mentisrex_commit}`  ",
            "",
            "---",
            "",
            "## Promotion Decision",
            "",
            f"**State:** `{p.state.value.upper()}`  ",
            f"**Confidence Score:** {p.confidence_score:.2f} / 1.00  ",
            "",
        ]

        if p.blocking_issues:
            lines += ["**Blocking Issues:**"]
            lines += [f"- {i}" for i in p.blocking_issues]
            lines.append("")

        lines += [
            "**Next Steps:**",
            *[f"- {s}" for s in p.next_steps],
            "",
            "---",
            "",
            "## Performance Metrics",
            "",
            "| Metric | Value |",
            "|---|---|",
            f"| Total Return | {m.total_return:+.2%} |",
            f"| CAGR | {m.cagr:+.2%} |",
            f"| Annualized Volatility | {m.annualized_volatility:.2%} |",
            f"| Sharpe Ratio | {m.sharpe_ratio:.3f} |",
            f"| Sortino Ratio | {m.sortino_ratio:.3f} |",
            f"| Calmar Ratio | {m.calmar_ratio:.3f} |",
            f"| Max Drawdown | {m.max_drawdown:.2%} |",
            f"| Avg Drawdown | {m.avg_drawdown:.2%} |",
            f"| Recovery Time | {m.recovery_time_days:.0f} days |",
            f"| Win Rate | {m.win_rate:.1%} |",
            f"| Profit Factor | {m.profit_factor:.2f} |",
            f"| Expectancy | {m.expectancy:+.2f} |",
            f"| Annual Turnover | {m.annual_turnover:.1f}x |",
            "",
            "### Tail Risk",
            "",
            "| Metric | Value |",
            "|---|---|",
            f"| VaR 95% (1-day) | {m.var_95:.2%} |",
            f"| VaR 99% (1-day) | {m.var_99:.2%} |",
            f"| CVaR 95% (1-day) | {m.cvar_95:.2%} |",
            f"| Skewness | {m.skewness:.3f} |",
            f"| Excess Kurtosis | {m.excess_kurtosis:.3f} |",
            f"| Tail Ratio | {m.tail_ratio:.2f} |",
            "",
            "### Cost Analysis",
            "",
            "| Metric | Value |",
            "|---|---|",
            f"| TC Drag | {m.tc_drag_bps:.1f} bps/yr |",
            f"| Slippage Drag | {m.slippage_drag_bps:.1f} bps/yr |",
            f"| Capacity Estimate | {f'{m.capacity_estimate_mm:.0f} $M' if m.capacity_estimate_mm > 0 else 'unknown'} |",
            "",
            "---",
            "",
            "## Statistical Evidence",
            "",
            "| Test | Value |",
            "|---|---|",
            f"| Bootstrap Sharpe CI 95% | [{bs.ci_lower:.3f}, {bs.ci_upper:.3f}] |",
            f"| Bootstrap Bias | {bs.bias:+.3f} |",
            f"| Permutation p-value | {self.permutation.pvalue:.4f} "
            f"(n={self.permutation.n_permutations}) |",
            f"| Bonferroni adj p-value | {self.bonferroni_adj_pvalue:.4f} "
            f"(n_trials={self.n_trials}) |",
            "",
            "---",
            "",
            "## Robustness Assessment",
            "",
            f"**Overall Robust:** {'Yes' if r.is_robust else 'No'}  ",
            "",
            f"### Walk-Forward ({len(r.walk_forward_sharpes)} folds)",
            "",
            f"Sharpes: {[round(s, 3) for s in r.walk_forward_sharpes]}  ",
            f"CV: {r.walk_forward_cv:.3f}  ",
            f"Worst fold: {r.worst_fold_sharpe:.3f}  ",
            "",
            "### Regime Performance",
            "",
        ]

        if r.regime_stats:
            lines += [
                "| Regime | N Days | Sharpe | Return | Max DD |",
                "|---|---|---|---|---|",
                *[
                    f"| {rs.label} | {rs.n_days} | {rs.sharpe:.3f} | {rs.total_return:.2%} | "
                    f"{rs.max_drawdown:.2%} |"
                    for rs in r.regime_stats
                ],
                "",
            ]
        else:
            lines += ["*(insufficient data for regime analysis)*", ""]

        lines += [
            "### Cost Sensitivity",
            "",
            f"TC breakeven: **{r.tc_sweep.breakeven:.0f} bps**  ",
            f"Slippage breakeven: **{r.slippage_sweep.breakeven:.0f} bps**  ",
            "",
        ]

        if r.weaknesses:
            lines += ["### Weaknesses", ""]
            lines += [f"- {w}" for w in r.weaknesses]
            lines.append("")

        if r.strengths:
            lines += ["### Strengths", ""]
            lines += [f"- {s}" for s in r.strengths]
            lines.append("")

        if self.known_weaknesses:
            lines += ["### Known Failure Modes", ""]
            lines += [f"- {w}" for w in self.known_weaknesses]
            lines.append("")

        lines += [
            "---",
            "",
            "## Audit Trail",
            "",
            "| Field | Value |",
            "|---|---|",
            f"| Python | {self.audit.python_version.split()[0]} |",
            f"| Git Commit | `{self.audit.mentisrex_commit}` |",
            f"| Config Hash | `{self.audit.config_hash}` |",
            f"| Dataset Fingerprint | `{self.audit.dataset_fingerprint}` |",
            f"| Random Seed | {self.audit.random_seed} |",
            *[f"| {k} | {v} |" for k, v in self.audit.key_package_versions.items()],
        ]

        return "\n".join(lines)

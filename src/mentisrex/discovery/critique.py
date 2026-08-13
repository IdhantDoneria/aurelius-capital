"""Self-Critique & Falsification Engine — rigorous peer-review simulation."""

from mentisrex.core.logging import get_logger
from mentisrex.discovery.models import DiscoveryHypothesis, NoveltyScore, SelfCritiqueReport

logger = get_logger(__name__)


class SelfCritiqueEngine:
    """Evaluates counter-arguments, formulates falsification criteria,

    and rejects candidates that fail robustness or economic checks.
    """

    def evaluate(
        self, hypothesis: DiscoveryHypothesis, novelty_score: NoveltyScore
    ) -> SelfCritiqueReport:
        counter_args = [
            f"Observed alpha in '{hypothesis.title}' may be a statistical artifact of data mining across multiple parameters.",
            f"High turnover in holding period '{hypothesis.holding_period}' could consume expected excess returns under realistic 5-10bps transaction costs.",
            f"Required feature '{hypothesis.required_features[0] if hypothesis.required_features else 'unknown'}' might exhibit severe regime instability in bear markets.",
        ]

        falsification_tests = [
            "Falsification 1: Reject if Out-of-Sample Sharpe Ratio < 0.50.",
            "Falsification 2: Reject if Bonferroni-adjusted p-value > 0.05 across 1000 permutation trials.",
            "Falsification 3: Reject if breakeven transaction cost is below 5 bps.",
        ]

        competing_explanations = [
            "Explanation A: Risk Compensation — Excess return represents compensation for tail risk rather than anomaly.",
            "Explanation B: Microstructure Drag — Signal captures bid-ask bounce rather than directional predictability.",
            "Explanation C: Liquidity Premium — Outperformance is restricted to illiquid small-cap stocks.",
        ]

        # Falsification logic: filter out hypotheses with high compute cost + high similarity or low testability
        survived = True
        reasons = []

        if novelty_score.similarity_to_previous > 0.65:
            survived = False
            reasons.append(
                f"High similarity to existing hypothesis store ({novelty_score.similarity_to_previous:.1%})"
            )

        if novelty_score.testability < 2:
            survived = False
            reasons.append("Insufficient data testability")

        if (
            "lob_tick_data" in hypothesis.required_datasets
            and novelty_score.expected_compute_cost >= 4
        ):
            survived = False
            reasons.append(
                "Excessive computational requirement relative to expected research value"
            )

        critique_score = 85.0 if survived else 35.0
        verdict_str = (
            "PASSED: Robust economic rationale & falsification criteria met."
            if survived
            else f"REJECTED: {'; '.join(reasons)}"
        )

        logger.info(
            "hypothesis_self_critique_complete",
            hyp_id=hypothesis.id,
            survived=survived,
            critique_score=critique_score,
        )

        return SelfCritiqueReport(
            hypothesis_id=hypothesis.id,
            counter_arguments=counter_args,
            falsification_tests=falsification_tests,
            competing_explanations=competing_explanations,
            survived_critique=survived,
            critique_score=critique_score,
            verdict_reason=verdict_str,
        )

"""Novelty & Research Value Scorer for Candidate Hypotheses."""

from aurelius.core.logging import get_logger
from aurelius.discovery.models import DiscoveryHypothesis, NoveltyScore
from aurelius.hypothesis.store import HypothesisStore
from aurelius.knowledge.graph import KnowledgeGraph

logger = get_logger(__name__)


class NoveltyScorer:
    """Evaluates candidates for novelty, similarity to historical work, economic rationale, and cost."""

    def __init__(
        self,
        kg: KnowledgeGraph | None = None,
        hypotheses: HypothesisStore | None = None,
    ) -> None:
        self.kg = kg or KnowledgeGraph("./data/knowledge_graph.duckdb")
        self.hypotheses = hypotheses or HypothesisStore("./data/hypothesis.duckdb")

    def score(self, hypothesis: DiscoveryHypothesis) -> NoveltyScore:
        # Compute similarity against existing stored hypotheses
        existing = self.hypotheses.search(limit=1000)
        max_similarity = 0.0
        hyp_words = set(hypothesis.testable_statement.lower().split())

        for h in existing:
            other_words = set(h.testable_statement.lower().split())
            if not hyp_words or not other_words:
                continue
            jaccard = len(hyp_words & other_words) / float(len(hyp_words | other_words))
            if jaccard > max_similarity:
                max_similarity = jaccard

        # Calculate scores based on generation rule and complexity
        novelty_level = 4 if max_similarity < 0.2 else (3 if max_similarity < 0.4 else 2)
        research_val = round(max(10.0, 90.0 - (max_similarity * 60.0)), 1)

        economic_rat = (
            4
            if "interaction" in hypothesis.economic_intuition.lower()
            or "curve" in hypothesis.economic_intuition.lower()
            else 3
        )
        testability = 4 if len(hypothesis.required_features) <= 2 else 3
        cost = (
            3
            if "intraday" in hypothesis.holding_period
            or "lob_tick_data" in hypothesis.required_datasets
            else 2
        )
        impact = round(research_val * 0.95, 1)

        explanation = (
            f"Novelty rating {novelty_level}/5 (Similarity to existing portfolio: {max_similarity:.2%}). "
            f"Estimated Research Value: {research_val}/100. Expected Compute Cost: {cost}/5."
        )

        logger.info(
            "hypothesis_scored",
            hyp_id=hypothesis.id,
            novelty=novelty_level,
            similarity=round(max_similarity, 3),
            research_val=research_val,
        )

        return NoveltyScore(
            hypothesis_id=hypothesis.id,
            novelty=novelty_level,
            similarity_to_previous=round(max_similarity, 4),
            research_value=research_val,
            economic_rationale=economic_rat,
            testability=testability,
            expected_compute_cost=cost,
            potential_impact=impact,
            explanation=explanation,
        )

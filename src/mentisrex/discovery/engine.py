"""Alpha Discovery Engine Orchestrator."""

from datetime import UTC, datetime

from mentisrex.core.logging import get_logger
from mentisrex.corpus.store import CorpusStore
from mentisrex.director.director import ResearchDirector
from mentisrex.discovery.critique import SelfCritiqueEngine
from mentisrex.discovery.generator import AlphaHypothesisGenerator
from mentisrex.discovery.models import DiscoveryCycleResult, DiscoveryHypothesis
from mentisrex.discovery.scorer import NoveltyScorer
from mentisrex.discovery.synthesis import KnowledgeSynthesizer
from mentisrex.hypothesis.models import HypothesisRecord
from mentisrex.hypothesis.store import HypothesisStore
from mentisrex.knowledge.graph import KnowledgeGraph
from mentisrex.research.store import ResearchStore

logger = get_logger(__name__)


class AlphaDiscoveryEngine:
    """Orchestrates the complete 6-part Alpha Discovery lifecycle:

    Synthesis -> Generation -> Scoring -> Explanation -> Self-Critique -> Submission/Archive.
    """

    def __init__(
        self,
        kg: KnowledgeGraph | None = None,
        corpus: CorpusStore | None = None,
        hypotheses: HypothesisStore | None = None,
        research: ResearchStore | None = None,
    ) -> None:
        self.kg = kg or KnowledgeGraph("./data/knowledge_graph.duckdb")
        self.corpus = corpus or CorpusStore("./data/corpus.duckdb")
        self.hypotheses = hypotheses or HypothesisStore("./data/hypothesis.duckdb")
        self.research = research or ResearchStore("./data/research.duckdb")

        self.synthesizer = KnowledgeSynthesizer(
            kg=self.kg, corpus=self.corpus, hypotheses=self.hypotheses, research=self.research
        )
        self.generator = AlphaHypothesisGenerator()
        self.scorer = NoveltyScorer(kg=self.kg, hypotheses=self.hypotheses)
        self.critique = SelfCritiqueEngine()
        self.director = ResearchDirector(
            kg=self.kg, hypotheses=self.hypotheses, research=self.research
        )

    def run_discovery_cycle(self, candidate_limit: int = 5) -> DiscoveryCycleResult:
        logger.info("alpha_discovery_cycle_start", candidate_limit=candidate_limit)

        # Part 1: Knowledge Synthesis
        synthesis_report = self.synthesizer.synthesize()

        # Part 2: Hypothesis Generation
        candidates = self.generator.generate_candidates(synthesis_report, limit=candidate_limit)

        approved: list[DiscoveryHypothesis] = []
        rejected: list[DiscoveryHypothesis] = []

        for candidate in candidates:
            # Part 3: Novelty Scoring
            novelty = self.scorer.score(candidate)

            # Part 5: Self-Critique & Falsification
            critique_res = self.critique.evaluate(candidate, novelty)

            if critique_res.survived_critique:
                candidate.status = "Approved"
                approved.append(candidate)

                # Part 6: Send into Experiment Orchestration Framework (HypothesisStore)
                rec = HypothesisRecord(
                    id=candidate.id,
                    parent_papers=candidate.supporting_literature,
                    research_category=candidate.research_category,
                    economic_intuition=candidate.economic_intuition,
                    testable_statement=candidate.testable_statement,
                    expected_behavior=candidate.expected_behavior,
                    asset_classes=candidate.asset_classes,
                    required_datasets=candidate.required_datasets,
                    required_features=candidate.required_features,
                    holding_period=candidate.holding_period,
                    expected_risks=candidate.expected_weaknesses,
                    confidence_score=round(critique_res.critique_score / 100.0, 2),
                    assumptions=[candidate.why_it_exists],
                    dependencies=candidate.required_features,
                    validation_requirements=candidate.validation_plan,
                    status="Active",
                    version=1,
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                    researcher="AlphaDiscoveryEngine",
                    generation_method=candidate.generation_rule,
                )
                self.hypotheses.insert(rec)
                logger.info("alpha_hypothesis_submitted_to_orchestrator", hyp_id=candidate.id)
            else:
                candidate.status = "Rejected"
                candidate.rejection_reason = critique_res.verdict_reason
                rejected.append(candidate)
                logger.info(
                    "alpha_hypothesis_rejected",
                    hyp_id=candidate.id,
                    reason=candidate.rejection_reason,
                )

        logger.info(
            "alpha_discovery_cycle_complete",
            generated=len(candidates),
            approved=len(approved),
            rejected=len(rejected),
        )

        return DiscoveryCycleResult(
            synthesis=synthesis_report,
            candidates_generated=len(candidates),
            approved_hypotheses=approved,
            rejected_hypotheses=rejected,
        )

"""Unit tests for CitationGraph."""

from aurelius.corpus.citation import CitationGraph
from aurelius.corpus.models import CitationEdgeType


def test_citation_lineage_tracking() -> None:
    cg = CitationGraph()

    paper_id = "doc_fama_french_1993"
    hyp_id = "hyp_three_factor_alpha"
    exp_id = "exp_stat_arb_vol"
    strat_id = "strat_prod_momentum"

    # Paper -> Hypothesis
    cg.add_edge(
        hyp_id, paper_id, CitationEdgeType.HYPOTHESIS_ORIGIN, "Originating paper for hypothesis"
    )

    # Hypothesis -> Experiment
    cg.add_edge(exp_id, hyp_id, CitationEdgeType.HYPOTHESIS_ORIGIN, "Experiment testing hypothesis")
    cg.add_edge(exp_id, paper_id, CitationEdgeType.EXPERIMENT_CITE, "Experiment cites paper")

    # Strategy -> Experiment
    cg.add_edge(
        strat_id, exp_id, CitationEdgeType.STRATEGY_SUPPORT, "Strategy supported by experiment"
    )

    origins = cg.get_hypothesis_origin(hyp_id)
    assert paper_id in origins

    exp_cites = cg.get_experiment_citations(exp_id)
    assert paper_id in exp_cites

    lit = cg.get_strategy_supporting_literature(strat_id)
    assert paper_id in lit

    report = cg.get_provenance_report(strat_id, "strategy")
    assert report.target_id == strat_id
    assert len(report.lineage_path) >= 2

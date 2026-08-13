"""Citation tracking and literature provenance engine."""

from mentisrex.corpus.models import CitationEdge, CitationEdgeType, ProvenanceReport


class CitationGraph:
    """Citation graph tracking relationships between literature, hypotheses,

    features, experiments, and production strategies.
    """

    def __init__(self) -> None:
        self.edges: list[CitationEdge] = []

    def add_edge(
        self,
        source_id: str,
        target_id: str,
        edge_type: CitationEdgeType = CitationEdgeType.PAPER_REFERENCE,
        description: str = "",
    ) -> CitationEdge:
        # Idempotent check
        for e in self.edges:
            if e.source_id == source_id and e.target_id == target_id and e.edge_type == edge_type:
                return e

        edge = CitationEdge(
            source_id=source_id,
            target_id=target_id,
            edge_type=edge_type,
            description=description,
        )
        self.edges.append(edge)
        return edge

    def get_citations_from(self, source_id: str) -> list[CitationEdge]:
        return [e for e in self.edges if e.source_id == source_id]

    def get_citations_to(self, target_id: str) -> list[CitationEdge]:
        return [e for e in self.edges if e.target_id == target_id]

    def get_hypothesis_origin(self, hypothesis_id: str) -> list[str]:
        """Which paper(s) originated this hypothesis?"""
        origins = []
        for e in self.edges:
            if e.source_id == hypothesis_id and e.edge_type == CitationEdgeType.HYPOTHESIS_ORIGIN:
                origins.append(e.target_id)
            elif e.target_id == hypothesis_id and e.edge_type == CitationEdgeType.HYPOTHESIS_ORIGIN:
                origins.append(e.source_id)
        return list(set(origins))

    def get_experiment_citations(self, experiment_id: str) -> list[str]:
        """Which paper(s) does this experiment cite?"""
        cites = []
        for e in self.edges:
            if e.source_id == experiment_id and e.edge_type == CitationEdgeType.EXPERIMENT_CITE:
                cites.append(e.target_id)
        return list(set(cites))

    def get_strategy_supporting_literature(self, strategy_id: str) -> list[str]:
        """Which production strategy is supported by which literature papers?"""
        direct_papers = [
            e.target_id
            for e in self.edges
            if e.source_id == strategy_id and e.edge_type == CitationEdgeType.STRATEGY_SUPPORT
        ]

        # Trace via experiments and hypotheses
        connected_experiments = [
            e.target_id
            for e in self.edges
            if e.source_id == strategy_id
            and e.edge_type in (CitationEdgeType.EXPERIMENT_CITE, CitationEdgeType.STRATEGY_SUPPORT)
        ]

        indirect_papers = []
        for exp_id in connected_experiments:
            indirect_papers.extend(self.get_experiment_citations(exp_id))
            # Also trace hypothesis origin from experiment
            hyp_ids = [
                e.target_id
                for e in self.edges
                if e.source_id == exp_id and e.edge_type == CitationEdgeType.HYPOTHESIS_ORIGIN
            ]
            for h_id in hyp_ids:
                indirect_papers.extend(self.get_hypothesis_origin(h_id))

        return list(set(direct_papers + indirect_papers))

    def get_provenance_report(
        self, target_id: str, target_type: str = "strategy"
    ) -> ProvenanceReport:
        """Generates complete provenance report for a strategy, experiment, or hypothesis."""
        citations = self.get_citations_from(target_id) + self.get_citations_to(target_id)
        supporting_papers = []
        supporting_hypotheses = []
        supporting_experiments = []
        lineage_path = [target_id]

        for e in citations:
            other_id = e.target_id if e.source_id == target_id else e.source_id
            lineage_path.append(other_id)
            if "doc_" in other_id or "paper" in other_id:
                supporting_papers.append(
                    {"id": other_id, "edge_type": e.edge_type, "description": e.description}
                )
            elif "hyp_" in other_id or "hypothesis" in other_id:
                supporting_hypotheses.append(
                    {"id": other_id, "edge_type": e.edge_type, "description": e.description}
                )
            elif "exp_" in other_id or "experiment" in other_id:
                supporting_experiments.append(
                    {"id": other_id, "edge_type": e.edge_type, "description": e.description}
                )

        return ProvenanceReport(
            target_id=target_id,
            target_type=target_type,
            supporting_papers=supporting_papers,
            supporting_hypotheses=supporting_hypotheses,
            supporting_experiments=supporting_experiments,
            lineage_path=list(set(lineage_path)),
        )

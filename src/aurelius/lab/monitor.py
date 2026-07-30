"""Laboratory monitoring — one health snapshot across every subsystem.

Pure composition: reads the stores, the Director, the Intelligence engine, and
the audit journal. Owns no state. Every metric the Phase-18 spec names maps to a
key here.
"""

from __future__ import annotations

from typing import Any

from aurelius.lab.supervisor import Supervisor


class LabMonitor:
    def __init__(self, supervisor: Supervisor) -> None:
        self.sup = supervisor

    def snapshot(self) -> dict[str, Any]:
        sup = self.sup
        learning = sup.intel.director.learning_stats()
        se = sup.intel.self_evaluation()
        kg_stats = sup.director._safe(sup.kg.stats)
        qc = sup.director._safe(sup.kg.qc_report)
        qc = qc if isinstance(qc, dict) else {}
        failures = sup.journal.failure_rate()
        backlog = [r for r in sup.director.prioritize() if r.decision in ("research_now", "delay")]
        backlog_load = sum(float(r.resources["runtime_min"]) for r in backlog)

        node_total = (
            sum(t.get("count", 0) for t in kg_stats.get("nodes_by_type", []))
            if isinstance(kg_stats, dict)
            else 0
        )

        health_issues = []
        if qc.get("health") == "issues_detected":
            health_issues.append("knowledge_graph_qc")
        if sup.last_cycle and sup.last_cycle.get("failed"):
            health_issues.append("last_cycle_had_failures")
        if failures["job_failure_rate"] > 0.2:
            health_issues.append("elevated_job_failure_rate")

        return {
            "research_throughput": {
                "hypotheses_total": sup.hyp.stats().get("total", 0),
                "by_status": sup.hyp.stats().get("by_status", {}),
            },
            "experiment_throughput": {
                "experiments_recorded": learning.get("experiments_recorded", 0),
                "per_week": learning.get("velocity_experiments_per_week"),
                "accept_rate": learning.get("overall_accept_rate"),
            },
            "knowledge_growth": {
                "nodes_total": node_total,
                "nodes_by_type": kg_stats.get("nodes_by_type", []),
                "weekly_growth": kg_stats.get("weekly_growth", []),
            },
            "system_health": {
                "status": "ok" if not health_issues else "degraded",
                "issues": health_issues,
                "kg_health": qc.get("health"),
                "validation_false_positive_rate": se.get("validation_false_positive_rate"),
            },
            "research_failures": {
                "job_failure_rate": failures["job_failure_rate"],
                "jobs": failures["jobs"],
                "experiment_reject_rate": round(1 - (learning.get("overall_accept_rate") or 0), 3)
                if learning.get("overall_accept_rate") is not None
                else None,
            },
            "queue_health": {
                "backlog_size": len(backlog),
                "duplicate_research_rate": se.get("duplicate_research_rate"),
                "cycles_observed": failures["cycles_considered"],
            },
            "resource_utilization": {
                "backlog_runtime_min": round(backlog_load, 1),
                "cycle_budget_min": sup.cycle_budget_min,
                "budget_pressure": round(backlog_load / sup.cycle_budget_min, 2)
                if sup.cycle_budget_min
                else None,
            },
            "last_cycle": sup.last_cycle,
            "recent_cycles": sup.journal.recent_cycles(5),
        }


if __name__ == "__main__":
    import tempfile
    from pathlib import Path

    from aurelius.hypothesis.store import HypothesisStore
    from aurelius.knowledge.graph import KnowledgeGraph
    from aurelius.lab.journal import LabJournal
    from aurelius.literature.store import LiteratureStore
    from aurelius.paper.outcomes import PaperOutcomeStore
    from aurelius.research.store import ResearchStore

    tmp = Path(tempfile.mkdtemp())
    sup = Supervisor(
        literature=LiteratureStore(":memory:"),
        hypotheses=HypothesisStore(":memory:"),
        research=ResearchStore(":memory:"),
        kg=KnowledgeGraph(":memory:"),
        paper=PaperOutcomeStore(":memory:"),
        journal=LabJournal(tmp / "j.jsonl"),
    )
    snap = LabMonitor(sup).snapshot()
    for key in (
        "research_throughput",
        "experiment_throughput",
        "knowledge_growth",
        "system_health",
        "research_failures",
        "queue_health",
        "resource_utilization",
    ):
        assert key in snap, key
    assert snap["system_health"]["status"] in ("ok", "degraded")
    print("lab monitor self-check ok:", snap["system_health"]["status"])

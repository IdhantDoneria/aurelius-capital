"""Research Director — orchestrates scoring, decisions, roadmap, resources, learning.

Reads live state from the Knowledge Graph + hypothesis/research stores. Holds no
state of its own: every call recomputes from the persisted institutional memory,
so a decision is always current and never stale. Steps 2-6 of the Phase-16 spec.
"""

from __future__ import annotations

import enum
import duckdb
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from aurelius.core.logging import get_logger
from aurelius.director.scoring import (
    FactorScores,
    ResearchContext,
    score_hypothesis,
    top_drivers,
    weakest_factors,
)
from aurelius.hypothesis.models import HypothesisRecord
from aurelius.hypothesis.store import HypothesisStore
from aurelius.knowledge.graph import KnowledgeGraph
from aurelius.research.store import ResearchStore

logger = get_logger(__name__)


class Decision(enum.StrEnum):
    RESEARCH_NOW = "research_now"
    DELAY = "delay"
    REJECT = "reject"
    MERGE = "merge"
    ARCHIVE = "archive"
    ESCALATE = "escalate"


# Priority thresholds on the overall score. Calibration knobs.
_RESEARCH_NOW_MIN = 0.65
_DELAY_MIN = 0.45
_MERGE_NOVELTY_MAX = 0.35  # below this + has near-dupes → merge
_DEAD_CATEGORY_TRIALS = 3  # category with this many trials and ~0 accepts → reject
_DEAD_CATEGORY_RATE = 0.05
_ESCALATE_CONF = 0.80  # high conviction but low computed score → human review

# Compute budgets per queue horizon, in experiment-minutes. Greedy bin-pack.
_QUEUE_BUDGET_MIN = {
    "daily": 8 * 60,
    "weekly": 40 * 60,
    "monthly": 160 * 60,
    "quarterly": 10**9,  # roadmap = everything actionable, ranked
}


@dataclass
class Ranked:
    hypothesis_id: str
    category: str
    statement: str
    status: str
    overall: float
    decision: str
    explanation: str
    factors: dict[str, float]
    resources: dict[str, float | int | list]

    def summary(self) -> dict:
        d = asdict(self)
        return d


class ResearchDirector:
    def __init__(
        self,
        kg: KnowledgeGraph | None = None,
        hypotheses: HypothesisStore | None = None,
        research: ResearchStore | None = None,
    ) -> None:
        if kg is None or hypotheses is None or research is None:
            from aurelius.infrastructure.config.settings import get_settings

            s = get_settings()
            kg = kg or KnowledgeGraph(s.knowledge_graph_path)
            hypotheses = hypotheses or HypothesisStore()
            research = research or ResearchStore()
        self.kg = kg
        self.hyp = hypotheses
        self.research = research

    # ── Context (feeds scorer + continuous learning) ────────────────────────────

    def _load_context(self) -> ResearchContext:
        known_datasets = self._kg_labels("dataset")
        known_features = self._kg_labels("feature")

        cat_counts: Counter[str] = Counter()
        total = 0
        for h in self.hyp.search(limit=10_000):
            if h.status == "Rejected":
                continue
            cat_counts[h.research_category or "unknown"] += 1
            total += 1

        success, trials = self._category_outcomes()
        return ResearchContext(
            known_datasets=known_datasets,
            known_features=known_features,
            category_counts=dict(cat_counts),
            category_success=success,
            category_trials=trials,
            total_hypotheses=total,
        )

    def _kg_labels(self, node_type: str) -> set[str]:
        try:
            rows = self.kg.raw_query(
                "SELECT DISTINCT LOWER(label) AS l FROM kg_nodes "
                "WHERE type = ? AND superseded_by IS NULL",
                [node_type],
            )
            return {r["l"] for r in rows if r.get("l")}
        except duckdb.Error:  # KG empty / not migrated yet — degrade to neutral scoring
            return set()

    def _category_outcomes(self) -> tuple[dict[str, float], dict[str, int]]:
        """Per-category accept rate + trial count from recorded experiments.

        Maps experiment.hypothesis_id → category via the full hypothesis store;
        experiments with no matching record bucket as 'unknown'.
        """
        id_to_cat = {
            h.id: (h.research_category or "unknown") for h in self.hyp.search(limit=10_000)
        }
        rows = self.research._query("SELECT hypothesis_id, verdict FROM experiments", [])
        accepts: Counter[str] = Counter()
        totals: Counter[str] = Counter()
        for r in rows:
            cat = id_to_cat.get(r["hypothesis_id"], "unknown")
            totals[cat] += 1
            if r["verdict"] == "accept":
                accepts[cat] += 1
        success = {c: accepts[c] / totals[c] for c in totals}
        return success, dict(totals)

    # ── Decision engine (Step 5) ────────────────────────────────────────────────

    def _decide(
        self, h: HypothesisRecord, f: FactorScores, ctx: ResearchContext
    ) -> tuple[Decision, str]:
        cat = h.research_category or "unknown"

        if h.status == "Rejected":
            reason = h.rejection_reason or "no reason recorded"
            return Decision.ARCHIVE, f"Already rejected: {reason}."
        if h.status == "Promoted":
            return Decision.ARCHIVE, "Already promoted to production — research complete."

        if h.similar_to and f.novelty < _MERGE_NOVELTY_MAX:
            return Decision.MERGE, (
                f"Novelty {f.novelty:.2f} below {_MERGE_NOVELTY_MAX}; near-duplicate of "
                f"{h.similar_to[0]}. Merge to avoid redundant work."
            )

        trials = ctx.category_trials.get(cat, 0)
        rate = ctx.category_success.get(cat, None)
        if trials >= _DEAD_CATEGORY_TRIALS and rate is not None and rate <= _DEAD_CATEGORY_RATE:
            return Decision.REJECT, (
                f"Category '{cat}' has {trials} experiments at {rate:.0%} accept rate — "
                f"repeatedly failing area. Reject unless the angle is materially new."
            )

        if f.data_availability < 0.5 or f.feature_availability < 0.5:
            missing = []
            if f.data_availability < 0.5:
                missing.append("datasets")
            if f.feature_availability < 0.5:
                missing.append("features")
            return Decision.DELAY, (
                f"Blocked on {'/'.join(missing)}: required inputs not yet in the platform. "
                f"Delay until acquired (data_av={f.data_availability:.2f}, "
                f"feat_av={f.feature_availability:.2f})."
            )

        drivers = ", ".join(f"{k}={v:.2f}" for k, v in top_drivers(f))
        if f.overall >= _RESEARCH_NOW_MIN:
            return Decision.RESEARCH_NOW, (
                f"Priority {f.overall:.2f} ≥ {_RESEARCH_NOW_MIN}. Top drivers: {drivers}."
            )
        if f.overall >= _DELAY_MIN:
            weak = ", ".join(f"{k}={v:.2f}" for k, v in weakest_factors(f))
            return Decision.DELAY, (
                f"Priority {f.overall:.2f} in queue band [{_DELAY_MIN}, {_RESEARCH_NOW_MIN}). "
                f"Weakest: {weak}. Schedule behind higher-priority work."
            )
        if h.confidence_score >= _ESCALATE_CONF:
            return Decision.ESCALATE, (
                f"Researcher confidence {h.confidence_score:.2f} high but computed priority "
                f"{f.overall:.2f} low — conflict. Escalate for manual review."
            )
        weak = ", ".join(f"{k}={v:.2f}" for k, v in weakest_factors(f))
        return Decision.REJECT, (
            f"Priority {f.overall:.2f} below {_DELAY_MIN}. Weakest: {weak}. "
            f"Low expected research value."
        )

    # ── Resource estimation (Step 4) ────────────────────────────────────────────

    @staticmethod
    def estimate_resources(h: HypothesisRecord) -> dict:
        from aurelius.director.scoring import _HOLDING_COST, _has_ml

        freq = _HOLDING_COST.get(h.holding_period, 0.5)
        n_feat = len(h.required_features)
        n_assets = max(len(h.asset_classes), 1)
        ml = _has_ml(h)

        # Runtime scales with bar frequency, universe breadth, feature count.
        runtime_min = 5.0 * (1 + 4 * freq) * (1 + n_feat / 5) * (1 + n_assets / 3)
        if ml:
            runtime_min *= 4
        memory_gb = round(1.0 + 0.5 * n_feat + 2.0 * n_assets * freq + (4 if ml else 0), 1)
        cpu_cores = min(16, 2 + n_assets + (2 if freq >= 0.6 else 0))
        gpu_count = 1 if ml else 0
        storage_gb = round(0.5 + n_assets * (5 if freq >= 0.6 else 1), 1)

        return {
            "runtime_min": round(runtime_min, 1),
            "memory_gb": memory_gb,
            "cpu_cores": cpu_cores,
            "gpu_count": gpu_count,
            "storage_gb": storage_gb,
            "dependencies": sorted(set(h.required_datasets + h.required_features)),
        }

    # ── Prioritisation (Step 1 tie-together) ────────────────────────────────────

    def prioritize(self, include_terminal: bool = False) -> list[Ranked]:
        """Score + decide every open hypothesis, ranked by priority desc."""
        ctx = self._load_context()
        ranked: list[Ranked] = []
        for h in self.hyp.search(limit=10_000):
            if not include_terminal and h.status in ("Rejected", "Promoted"):
                continue
            f = score_hypothesis(h, ctx)
            decision, why = self._decide(h, f, ctx)
            ranked.append(
                Ranked(
                    hypothesis_id=h.id,
                    category=h.research_category or "unknown",
                    statement=h.testable_statement,
                    status=h.status,
                    overall=round(f.overall, 4),
                    decision=decision.value,
                    explanation=why,
                    factors={k: round(v, 3) for k, v in f.as_dict().items()},
                    resources=self.estimate_resources(h),
                )
            )
        ranked.sort(key=lambda r: r.overall, reverse=True)
        return ranked

    # ── Research gap analysis (Step 2) ──────────────────────────────────────────

    def gap_analysis(self) -> dict:
        ctx = self._load_context()
        total = max(ctx.total_hypotheses, 1)
        shares = {c: n / total for c, n in ctx.category_counts.items()}
        over = sorted(
            (
                {"category": c, "share": round(s, 3), "count": ctx.category_counts[c]}
                for c, s in shares.items()
                if s > 0.30
            ),
            key=lambda d: d["share"],
            reverse=True,
        )
        # Under-researched = known category families with little/no coverage.
        set(ctx.category_counts)
        under = [
            {"category": c, "count": ctx.category_counts.get(c, 0)}
            for c in _KNOWN_CATEGORIES
            if ctx.category_counts.get(c, 0) <= 1
        ]
        failing = [
            {
                "category": c,
                "trials": ctx.category_trials[c],
                "accept_rate": round(ctx.category_success.get(c, 0.0), 3),
            }
            for c in ctx.category_trials
            if ctx.category_trials[c] >= _DEAD_CATEGORY_TRIALS
            and ctx.category_success.get(c, 0.0) <= _DEAD_CATEGORY_RATE
        ]
        return {
            "over_researched": over,
            "under_researched": under,
            "frequently_failing": failing,
            "missing_datasets": self._safe(self.kg.discover_research_gaps),
            "disconnected_clusters": self._safe(self.kg.discover_orphans),
            "successful_feature_families": self._safe(self.kg.discover_successful_feature_families),
            "repeated_failures": self._safe(self.kg.discover_repeated_failures),
            "unused_categories_note": (
                "under_researched compares the live backlog against a canonical "
                "category list; empty ones are unexplored opportunity."
            ),
        }

    # ── Roadmap / queues (Step 3) ───────────────────────────────────────────────

    def roadmap(self) -> dict:
        ranked = self.prioritize()
        actionable = [
            r for r in ranked if r.decision in (Decision.RESEARCH_NOW.value, Decision.DELAY.value)
        ]

        queues: dict[str, list] = {}
        for horizon, budget in _QUEUE_BUDGET_MIN.items():
            spent = 0.0
            picked: list = []
            for r in actionable:
                cost = float(r.resources["runtime_min"])  # type: ignore
                if spent + cost > budget and picked:
                    break
                picked.append(
                    {
                        "hypothesis_id": r.hypothesis_id,
                        "category": r.category,
                        "priority": r.overall,
                        "decision": r.decision,
                        "runtime_min": cost,
                    }
                )
                spent += cost
            queues[horizon] = picked
            queues[f"{horizon}_load_min"] = round(spent, 1)  # type: ignore
        queues["total_actionable"] = len(actionable)  # type: ignore
        return queues

    # ── Continuous learning (Step 6) ────────────────────────────────────────────

    def learning_stats(self) -> dict:
        rows = self.research._query("SELECT verdict, n_trials, created_at FROM experiments", [])
        verdicts = Counter(r["verdict"] for r in rows)
        total = sum(verdicts.values())
        success, trials = self._category_outcomes()

        # Research velocity: experiments per ISO week.
        by_week: Counter[str] = Counter()
        for r in rows:
            ts = r["created_at"]
            dt = ts if isinstance(ts, datetime) else datetime.fromisoformat(str(ts))
            by_week[dt.strftime("%G-W%V")] += 1
        weeks = len(by_week) or 1

        avg_trials = (sum(r["n_trials"] or 0 for r in rows) / total) if total else 0.0
        return {
            "experiments_recorded": total,
            "verdicts": dict(verdicts),
            "overall_accept_rate": round(verdicts.get("accept", 0) / total, 3) if total else None,
            "per_category_accept_rate": {c: round(v, 3) for c, v in success.items()},
            "per_category_trials": trials,
            "avg_trials_per_experiment": round(avg_trials, 2),  # data-mining pressure
            "velocity_experiments_per_week": round(total / weeks, 2),
            "weeks_active": weeks,
            "note": (
                "per_category_accept_rate feeds scoring.estimated_research_value on the "
                "next pass. Paper-trading false-positive rate not yet wired — add when "
                "the paper-trading journal links results back to hypothesis IDs."
            ),
        }

    def dashboard(self) -> dict:
        ranked = self.prioritize(include_terminal=True)
        by_decision: dict[str, int] = defaultdict(int)
        for r in ranked:
            by_decision[r.decision] += 1
        backlog = [
            r
            for r in ranked
            if r.decision
            in (Decision.RESEARCH_NOW.value, Decision.DELAY.value, Decision.ESCALATE.value)
        ]
        rmap = self.roadmap()
        total_load = sum(float(r.resources["runtime_min"]) for r in backlog)  # type: ignore
        return {
            "generated_at": datetime.now(UTC).isoformat(),
            "backlog_size": len(backlog),
            "decisions": dict(by_decision),
            "top_priorities": [r.summary() for r in ranked[:10]],
            "resource_utilization": {
                "backlog_runtime_min": round(total_load, 1),
                "daily_capacity_min": _QUEUE_BUDGET_MIN["daily"],
                "daily_load_min": rmap.get("daily_load_min", 0),
            },
            "knowledge_growth": self._safe(self.kg.stats),
            "learning": self.learning_stats(),
            "kg_health": self._safe(self.kg.qc_report),
            "daily_queue": rmap.get("daily", []),
        }

    @staticmethod
    def _safe(fn):  # KG may be empty/unmigrated in fresh installs
        try:
            return fn()
        except Exception as exc:
            return {"error": str(exc)}


# Canonical research category families used for gap detection. Extend freely —
# an empty one simply surfaces as an unexplored opportunity.
_KNOWN_CATEGORIES = [
    "factor_anomaly",
    "macro",
    "portfolio_construction",
    "risk_premia",
    "market_microstructure",
    "sentiment",
    "volatility",
    "cross_asset",
    "seasonality",
    "event_driven",
    "statistical_arbitrage",
    "machine_learning",
]


if __name__ == "__main__":
    from datetime import UTC, datetime

    kg = KnowledgeGraph(":memory:")
    hyp = HypothesisStore(":memory:")
    res = ResearchStore(":memory:")

    def _mk(id_, cat, conf, sim=(), ds=("crsp",), status="Draft") -> HypothesisRecord:
        now = datetime.now(UTC)
        return HypothesisRecord(
            id=id_,
            parent_papers=[],
            research_category=cat,
            economic_intuition="solid microeconomic reasoning " * 10,
            testable_statement=f"IF {cat} THEN alpha",
            expected_behavior="",
            asset_classes=["equities"],
            required_datasets=list(ds),
            required_features=["mom_12m"],
            holding_period="1_month",
            expected_risks=[],
            confidence_score=conf,
            assumptions=[],
            dependencies=[],
            validation_requirements=[],
            similar_to=list(sim),
            status=status,
            version=1,
            created_at=now,
            updated_at=now,
            researcher="llm",
            generation_method="llm",
        )

    # Seed KG so mom_12m/crsp count as available.
    kg.upsert_node("dataset:crsp", "dataset", "crsp")
    kg.upsert_node("feature:mom_12m", "feature", "mom_12m")

    hyp.insert(_mk("h1", "factor_anomaly", 0.8))
    hyp.insert(_mk("h2", "factor_anomaly", 0.4, sim=["h1", "x", "y"]))  # dupe
    hyp.insert(_mk("h3", "sentiment", 0.9, ds=("nonexistent_ds",)))  # blocked

    rd = ResearchDirector(kg=kg, hypotheses=hyp, research=res)
    ranked = rd.prioritize()
    assert len(ranked) == 3
    by_id = {r.hypothesis_id: r for r in ranked}
    assert by_id["h2"].decision == Decision.MERGE.value, by_id["h2"].decision
    assert by_id["h3"].decision == Decision.DELAY.value, by_id["h3"].decision  # missing dataset
    assert ranked[0].overall >= ranked[-1].overall
    rmap = rd.roadmap()
    assert "quarterly" in rmap
    dash = rd.dashboard()
    assert dash["backlog_size"] >= 1
    print("director self-check ok:", {r.hypothesis_id: r.decision for r in ranked})

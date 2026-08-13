"""Research Intelligence engine — meta-analysis, recommendations, trends, reports.

Composes the persisted research history (experiments, hypotheses, knowledge
graph) into actionable intelligence. Stateless: every call recomputes from
source, so intelligence is always current. Leans on ResearchDirector +
KnowledgeGraph where they already compute a signal; only net-new analytics
(experiment-derived meta-analysis, time-series trends, self-evaluation) live here.

Advisory only — nothing here mutates research results or production systems.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from mentisrex.core.logging import get_logger
from mentisrex.director.director import ResearchDirector
from mentisrex.hypothesis.store import HypothesisStore
from mentisrex.knowledge.graph import KnowledgeGraph
from mentisrex.paper.outcomes import PaperOutcomeStore
from mentisrex.research.store import ResearchStore

logger = get_logger(__name__)

_PERIOD_DAYS = {"daily": 1, "weekly": 7, "monthly": 30, "quarterly": 90, "annual": 365}

# A category needs at least this many experiments before "consistently fails"
# is a claim rather than noise.
_MIN_EVIDENCE = 3


def _as_dt(v: Any) -> datetime:
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=UTC)
    return datetime.fromisoformat(str(v)).replace(tzinfo=UTC)


def _split(s: str | None, sep: str) -> list[str]:
    return [x.strip() for x in (s or "").split(sep) if x.strip()]


def _entropy(counts: list[int]) -> float:
    """Shannon entropy normalised to 0..1 (research diversity)."""
    total = sum(counts)
    if total == 0 or len(counts) < 2:
        return 0.0
    h = -sum((n / total) * math.log2(n / total) for n in counts if n)
    return h / math.log2(len(counts))


class ResearchIntelligence:
    def __init__(
        self,
        kg: KnowledgeGraph | None = None,
        hypotheses: HypothesisStore | None = None,
        research: ResearchStore | None = None,
        paper: PaperOutcomeStore | None = None,
    ) -> None:
        if kg is None or hypotheses is None or research is None or paper is None:
            from mentisrex.infrastructure.config.settings import get_settings

            s = get_settings()
            kg = kg or KnowledgeGraph(s.knowledge_graph_path)
            hypotheses = hypotheses or HypothesisStore()
            research = research or ResearchStore()
            paper = paper or PaperOutcomeStore(s.paper_outcomes_path)
        self.kg = kg
        self.hyp = hypotheses
        self.research = research
        self.paper = paper
        self.director = ResearchDirector(kg=kg, hypotheses=hypotheses, research=research)

    # ── Learning engine (Step 1) — pull every source into one frame ─────────────

    def _experiments(self, since: datetime | None = None) -> list[dict]:
        rows = self.research._query(
            "SELECT hypothesis_id, created_at, dataset_version, features_used, "
            "verdict, reasons, oos_sharpe, n_trials, adjusted_pvalue FROM experiments",
            [],
        )
        if since:
            rows = [r for r in rows if _as_dt(r["created_at"]) >= since]
        return rows

    def _id_to_category(self) -> dict[str, str]:
        return {h.id: (h.research_category or "unknown") for h in self.hyp.search(limit=10_000)}

    # ── Meta-analysis (Step 2) ──────────────────────────────────────────────────

    def category_performance(self) -> list[dict]:
        """Which research categories consistently fail / succeed."""
        cat = self._id_to_category()
        agg: dict[str, dict] = defaultdict(lambda: {"n": 0, "accept": 0, "sharpe": []})
        for e in self._experiments():
            c = cat.get(e["hypothesis_id"], "unknown")
            a = agg[c]
            a["n"] += 1
            if e["verdict"] == "accept":
                a["accept"] += 1
            if e["oos_sharpe"] is not None:
                a["sharpe"].append(e["oos_sharpe"])
        out = []
        for c, a in agg.items():
            sh = a["sharpe"]
            out.append(
                {
                    "category": c,
                    "experiments": a["n"],
                    "accept_rate": round(a["accept"] / a["n"], 3) if a["n"] else 0.0,
                    "avg_oos_sharpe": round(sum(sh) / len(sh), 3) if sh else None,
                    "verdict": "consistently_fails"
                    if a["n"] >= _MIN_EVIDENCE and a["accept"] / a["n"] <= 0.1
                    else "productive"
                    if a["accept"] / max(a["n"], 1) >= 0.4
                    else "mixed",
                }
            )
        return sorted(out, key=lambda d: d["accept_rate"])

    def feature_families(self) -> list[dict]:
        """Which feature families produce the strongest evidence."""
        agg: dict[str, dict] = defaultdict(lambda: {"n": 0, "accept": 0, "sharpe": []})
        for e in self._experiments():
            for feat in _split(e["features_used"], ","):
                family = feat.split("_")[0] if "_" in feat else feat  # mom_12m -> mom
                a = agg[family]
                a["n"] += 1
                if e["verdict"] == "accept":
                    a["accept"] += 1
                if e["oos_sharpe"] is not None:
                    a["sharpe"].append(e["oos_sharpe"])
        out = []
        for fam, a in agg.items():
            if a["n"] < 1:
                continue
            sh = a["sharpe"]
            out.append(
                {
                    "feature_family": fam,
                    "used_in_experiments": a["n"],
                    "accept_rate": round(a["accept"] / a["n"], 3),
                    "avg_oos_sharpe": round(sum(sh) / len(sh), 3) if sh else None,
                }
            )
        return sorted(
            out, key=lambda d: (d["avg_oos_sharpe"] or -9, d["accept_rate"]), reverse=True
        )

    def statistical_test_effectiveness(self) -> list[dict]:
        """Which validation guards eliminate the most candidates (false positives).

        Reason strings on rejected experiments name the guard that fired.
        """
        fired: Counter[str] = Counter()
        rejects = 0
        for e in self._experiments():
            if e["verdict"] != "reject":
                continue
            rejects += 1
            for reason in _split(e["reasons"], "|"):
                # normalise to the guard, not the specific numbers
                key = reason.lower().split(":")[0].split("(")[0].strip()
                fired[key] += 1
        return [
            {
                "guard": g,
                "rejections_triggered": n,
                "share_of_rejects": round(n / rejects, 3) if rejects else 0.0,
            }
            for g, n in fired.most_common()
        ]

    def dataset_value(self) -> list[dict]:
        """Which datasets produce the highest research value."""
        agg: dict[str, dict] = defaultdict(lambda: {"n": 0, "accept": 0, "sharpe": []})
        for e in self._experiments():
            ds = e["dataset_version"] or "unknown"
            a = agg[ds]
            a["n"] += 1
            if e["verdict"] == "accept":
                a["accept"] += 1
            if e["oos_sharpe"] is not None:
                a["sharpe"].append(e["oos_sharpe"])
        out = []
        for ds, a in agg.items():
            sh = a["sharpe"]
            out.append(
                {
                    "dataset": ds,
                    "experiments": a["n"],
                    "accept_rate": round(a["accept"] / a["n"], 3) if a["n"] else 0.0,
                    "avg_oos_sharpe": round(sum(sh) / len(sh), 3) if sh else None,
                }
            )
        return sorted(out, key=lambda d: d["accept_rate"], reverse=True)

    def regime_sensitivity(self) -> dict:
        """Which market regimes invalidate hypotheses.

        REAL signal comes from paper-trading outcomes, which carry a regime label
        applied by the live system (`by_paper_regime`). Historical backtest
        experiments persist no tested-window dates, so their regime cannot be
        truthfully recovered — `by_backtest_year` is a coarse proxy only.
        """
        # Real: outcome mix per regime from live paper trading.
        by_regime: dict[str, Counter[str]] = defaultdict(Counter)
        for o in self.paper.all():
            by_regime[o.get("regime") or "unlabelled"][o["outcome"]] += 1
        paper_regime = []
        for regime, mix in sorted(by_regime.items()):
            n = sum(mix.values())
            failed = mix.get("failed", 0)
            paper_regime.append(
                {
                    "regime": regime,
                    "paper_runs": n,
                    "failure_rate": round(failed / n, 3) if n else 0.0,
                    "outcomes": dict(mix),
                }
            )

        # Proxy: backtest accept-rate by calendar year (year the experiment ran).
        by_year: dict[str, dict] = defaultdict(lambda: {"n": 0, "accept": 0})
        for e in self._experiments():
            y = _as_dt(e["created_at"]).strftime("%Y")
            by_year[y]["n"] += 1
            if e["verdict"] == "accept":
                by_year[y]["accept"] += 1
        year_series = [
            {
                "period": y,
                "experiments": v["n"],
                "accept_rate": round(v["accept"] / v["n"], 3) if v["n"] else 0.0,
            }
            for y, v in sorted(by_year.items())
        ]
        return {
            "by_paper_regime": paper_regime,
            "by_backtest_year": year_series,
            "note": "by_paper_regime is real (live regime labels). by_backtest_year "
            "is a proxy: experiments store no tested-window dates, so backtest "
            "regime cannot be recovered.",
        }

    def paper_trading_reliability(self) -> dict:
        """Did validation 'accept' verdicts survive live paper trading?

        The false-positive rate is validation's blind spot made measurable:
        hypotheses that passed statistical validation but failed in paper trading.
        """
        latest = self.paper.latest_per_hypothesis()
        decided = [o for o in latest if o["outcome"] != "running"]
        failed = [o for o in decided if o["outcome"] == "failed"]
        confirmed = [o for o in decided if o["outcome"] == "confirmed"]

        # Sharpe decay: paper vs backtest, where both are recorded.
        decays = [
            o["backtest_sharpe"] - o["paper_sharpe"]
            for o in latest
            if o.get("backtest_sharpe") is not None and o.get("paper_sharpe") is not None
        ]
        return {
            "hypotheses_in_paper": len(latest),
            "decided": len(decided),
            "false_positive_rate": round(len(failed) / len(decided), 3) if decided else None,
            "confirmation_rate": round(len(confirmed) / len(decided), 3) if decided else None,
            "avg_sharpe_decay": round(sum(decays) / len(decays), 3) if decays else None,
            "failed_hypotheses": [o["hypothesis_id"] for o in failed],
            "note": None
            if latest
            else "No paper-trading outcomes recorded yet — POST to /intel/paper-outcome "
            "from the live system to populate this.",
        }

    def meta_analysis(self) -> dict:
        return {
            "category_performance": self.category_performance(),
            "feature_families": self.feature_families(),
            "statistical_test_effectiveness": self.statistical_test_effectiveness(),
            "dataset_value": self.dataset_value(),
            "regime_sensitivity": self.regime_sensitivity(),
            "paper_trading_reliability": self.paper_trading_reliability(),
        }

    # ── Recommendations (Step 3) — every one cites evidence ─────────────────────

    def recommendations(self) -> list[dict]:
        recs: list[dict] = []
        cats = self.category_performance()
        feats = self.feature_families()

        def rec(rtype: str, action: str, target: str, rationale: str, evidence: dict) -> None:
            recs.append(
                {
                    "type": rtype,
                    "action": action,
                    "target": target,
                    "rationale": rationale,
                    "evidence": evidence,
                }
            )

        # Retire: consistently failing categories.
        for c in cats:
            if c["verdict"] == "consistently_fails":
                rec(
                    "retire",
                    "retire_category",
                    c["category"],
                    f"{c['experiments']} experiments at {c['accept_rate']:.0%} accept rate.",
                    {"experiments": c["experiments"], "accept_rate": c["accept_rate"]},
                )

        # Expand: productive categories + strongest feature families.
        for c in cats:
            if c["verdict"] == "productive":
                rec(
                    "expand",
                    "expand_category",
                    c["category"],
                    f"{c['accept_rate']:.0%} accept over {c['experiments']} experiments, "
                    f"avg OOS Sharpe {c['avg_oos_sharpe']}.",
                    {"accept_rate": c["accept_rate"], "avg_oos_sharpe": c["avg_oos_sharpe"]},
                )
        for f in feats[:3]:
            if (f["avg_oos_sharpe"] or 0) > 0.5:
                rec(
                    "build_feature",
                    "expand_feature_family",
                    f["feature_family"],
                    f"Strongest evidence: avg OOS Sharpe {f['avg_oos_sharpe']} across "
                    f"{f['used_in_experiments']} experiments.",
                    {
                        "avg_oos_sharpe": f["avg_oos_sharpe"],
                        "used_in_experiments": f["used_in_experiments"],
                    },
                )

        # Datasets to acquire: cited in literature, never tested (KG gap).
        for g in self.director._safe(self.kg.discover_research_gaps) or []:
            if isinstance(g, dict) and "dataset" in g:
                rec(
                    "acquire_dataset",
                    "acquire_dataset",
                    g["dataset"],
                    f"Cited in {g.get('paper_citations', '?')} papers but never tested.",
                    {"paper_citations": g.get("paper_citations")},
                )

        # Features to build: required by the backlog but absent from the platform.
        gaps = self.director.gap_analysis()
        for row in gaps.get("under_researched", [])[:5]:
            rec(
                "expand",
                "seed_hypotheses",
                row["category"],
                "Under-researched category — few or no active hypotheses.",
                {"active_hypotheses": row["count"]},
            )

        # Experiments worth repeating: inconclusive with promising Sharpe.
        for e in self._experiments():
            if e["verdict"] == "inconclusive" and (e["oos_sharpe"] or 0) >= 0.5:
                rec(
                    "repeat_experiment",
                    "repeat_with_more_data",
                    e["hypothesis_id"],
                    f"Inconclusive but OOS Sharpe {round(e['oos_sharpe'], 2)} — likely "
                    f"underpowered. Repeat with a longer window.",
                    {"oos_sharpe": e["oos_sharpe"], "n_trials": e["n_trials"]},
                )

        # Papers worth reviewing: behind the highest-confidence active hypotheses.
        top = sorted(
            (h for h in self.hyp.search(status="Active", limit=10_000)),
            key=lambda h: h.confidence_score,
            reverse=True,
        )[:3]
        for h in top:
            for pid in h.parent_papers[:2]:
                rec(
                    "review_paper",
                    "review_paper",
                    pid,
                    f"Parent of high-confidence hypothesis ({h.confidence_score:.2f}).",
                    {"hypothesis_id": h.id, "confidence": h.confidence_score},
                )

        # Experiments worth abandoning: repeated failures in dead categories.
        for c in cats:
            if c["verdict"] == "consistently_fails":
                rec(
                    "abandon",
                    "stop_experiments",
                    c["category"],
                    "Repeated rejections; capital of research time better spent elsewhere.",
                    {"accept_rate": c["accept_rate"], "experiments": c["experiments"]},
                )

        # Retire: strategies that passed validation but failed in paper trading.
        for o in self.paper.latest_per_hypothesis():
            if o["outcome"] == "failed":
                rec(
                    "retire",
                    "retire_strategy",
                    o["strategy_name"],
                    f"Passed validation but failed in paper trading "
                    f"(regime={o.get('regime') or 'n/a'}, paper Sharpe={o.get('paper_sharpe')}). "
                    f"Validation false positive.",
                    {
                        "hypothesis_id": o["hypothesis_id"],
                        "paper_sharpe": o.get("paper_sharpe"),
                        "regime": o.get("regime"),
                    },
                )
            elif o["outcome"] == "confirmed":
                rec(
                    "expand",
                    "scale_strategy",
                    o["strategy_name"],
                    f"Confirmed live in paper trading (paper Sharpe={o.get('paper_sharpe')}). "
                    f"Edge held up out-of-sample.",
                    {"hypothesis_id": o["hypothesis_id"], "paper_sharpe": o.get("paper_sharpe")},
                )

        return recs

    # ── Trend analysis (Step 4) ─────────────────────────────────────────────────

    def trends(self) -> dict:
        exps = self._experiments()
        weekly: dict[str, dict] = defaultdict(
            lambda: {"n": 0, "accept": 0, "pvals": [], "categories": set()}
        )
        cat = self._id_to_category()
        for e in exps:
            wk = _as_dt(e["created_at"]).strftime("%G-W%V")
            w = weekly[wk]
            w["n"] += 1
            if e["verdict"] == "accept":
                w["accept"] += 1
            if e["adjusted_pvalue"] is not None:
                w["pvals"].append(e["adjusted_pvalue"])
            w["categories"].add(cat.get(e["hypothesis_id"], "unknown"))

        productivity, success, validation_q, diversity = [], [], [], []
        for wk in sorted(weekly):
            w = weekly[wk]
            productivity.append({"week": wk, "experiments": w["n"]})
            success.append(
                {"week": wk, "accept_rate": round(w["accept"] / w["n"], 3) if w["n"] else 0}
            )
            validation_q.append(
                {
                    "week": wk,
                    "avg_adjusted_pvalue": round(sum(w["pvals"]) / len(w["pvals"]), 4)
                    if w["pvals"]
                    else None,
                }
            )
            diversity.append({"week": wk, "distinct_categories": len(w["categories"])})

        qc = self.director._safe(self.kg.qc_report)
        qc = qc if isinstance(qc, dict) else {}
        kg_stats = self.director._safe(self.kg.stats)
        kg_stats = kg_stats if isinstance(kg_stats, dict) else {}
        return {
            "research_productivity": productivity,
            "experiment_success_rate": success,
            "knowledge_growth": kg_stats.get("weekly_growth", []),
            "validation_quality": validation_q,
            "research_diversity": diversity,
            "technical_debt": {
                "orphan_nodes": qc.get("orphan_nodes"),
                "broken_edges": qc.get("broken_edge_sources", 0) + qc.get("broken_edge_targets", 0),
                "duplicate_labels": qc.get("duplicate_labels"),
            },
            "infrastructure_utilization": {
                "note": "Estimated backlog compute load; see /director/roadmap for budgets.",
                "backlog_runtime_min": sum(
                    float(r.resources["runtime_min"]) for r in self.director.prioritize()
                ),
            },
        }

    # ── Self-evaluation (Step 6) ────────────────────────────────────────────────

    def self_evaluation(self) -> dict:
        exps = self._experiments()
        n = len(exps)
        accepts = sum(1 for e in exps if e["verdict"] == "accept")
        learning = self.director.learning_stats()

        # Knowledge reuse: features used by >1 experiment / distinct features.
        feat_counts: Counter[str] = Counter()
        for e in exps:
            for f in set(_split(e["features_used"], ",")):
                feat_counts[f] += 1
        reused = sum(1 for v in feat_counts.values() if v > 1)
        reuse_rate = round(reused / len(feat_counts), 3) if feat_counts else 0.0

        # Duplicate research rate: hypotheses flagged as near-duplicates.
        all_h = self.hyp.search(limit=10_000)
        dup = sum(1 for h in all_h if h.similar_to)
        dup_rate = round(dup / len(all_h), 3) if all_h else 0.0

        # Hypothesis quality: promotion rate + confidence separation.
        promoted = [h for h in all_h if h.status == "Promoted"]
        rejected = [h for h in all_h if h.status == "Rejected"]
        decided = len(promoted) + len(rejected)

        def _avg_conf(hs):
            return round(sum(h.confidence_score for h in hs) / len(hs), 3) if hs else None

        # Decision-signal lift: does higher researcher confidence track acceptance?
        cat_conf = {h.id: h.confidence_score for h in all_h}
        hi = [e for e in exps if cat_conf.get(e["hypothesis_id"], 0) >= 0.7]
        lo = [e for e in exps if cat_conf.get(e["hypothesis_id"], 0) < 0.7]

        def _acc(es):
            return sum(1 for e in es if e["verdict"] == "accept") / len(es) if es else 0.0

        return {
            "research_efficiency": round(accepts / n, 3) if n else None,  # accepts/experiment
            "experiment_throughput_per_week": learning.get("velocity_experiments_per_week"),
            "avg_validation_quality": round(
                sum(e["adjusted_pvalue"] for e in exps if e["adjusted_pvalue"] is not None)
                / max(sum(1 for e in exps if e["adjusted_pvalue"] is not None), 1),
                4,
            )
            or None,
            "knowledge_reuse_rate": reuse_rate,
            "duplicate_research_rate": dup_rate,
            "hypothesis_quality": {
                "promotion_rate": round(len(promoted) / decided, 3) if decided else None,
                "avg_confidence_promoted": _avg_conf(promoted),
                "avg_confidence_rejected": _avg_conf(rejected),
            },
            "decision_signal_lift": round(_acc(hi) - _acc(lo), 3),  # >0 = confidence predicts
            "data_mining_pressure_avg_trials": learning.get("avg_trials_per_experiment"),
            # Real false-positive rate: validation accepts that failed in paper trading.
            "validation_false_positive_rate": self.paper_trading_reliability()[
                "false_positive_rate"
            ],
        }

    # ── Periodic reports (Step 5) ───────────────────────────────────────────────

    def report(self, period: str = "weekly") -> dict:
        if period not in _PERIOD_DAYS:
            raise ValueError(f"period must be one of {list(_PERIOD_DAYS)}")
        since = datetime.now(UTC) - timedelta(days=_PERIOD_DAYS[period])
        window = self._experiments(since=since)
        verdicts = Counter(e["verdict"] for e in window)
        cat = self._id_to_category()
        active_cats = Counter(cat.get(e["hypothesis_id"], "unknown") for e in window)
        recs = self.recommendations()

        markdown = self._render_markdown(period, since, window, verdicts, active_cats, recs)
        return {
            "period": period,
            "window_start": since.isoformat(),
            "generated_at": datetime.now(UTC).isoformat(),
            "experiments_in_window": len(window),
            "verdicts": dict(verdicts),
            "active_categories": dict(active_cats),
            "self_evaluation": self.self_evaluation(),
            "top_recommendations": recs[:8],
            "markdown": markdown,
        }

    def _render_markdown(self, period, since, window, verdicts, active_cats, recs) -> str:
        se = self.self_evaluation()
        lines = [
            f"# {period.capitalize()} Research Intelligence Report",
            f"_Window from {since.date()} to {datetime.now(UTC).date()}_",
            "",
            "## Activity",
            f"- Experiments run: **{len(window)}**",
            f"- Verdicts: {dict(verdicts) or 'none'}",
            f"- Active categories: {', '.join(active_cats) or 'none'}",
            "",
            "## Self-evaluation",
            f"- Research efficiency (accept/exp): **{se['research_efficiency']}**",
            f"- Throughput: {se['experiment_throughput_per_week']} exp/week",
            f"- Knowledge reuse: {se['knowledge_reuse_rate']}",
            f"- Duplicate research rate: {se['duplicate_research_rate']}",
            f"- Decision-signal lift: {se['decision_signal_lift']}",
            "",
            "## Top recommendations",
        ]
        if not recs:
            lines.append("- _No recommendations — insufficient evidence yet._")
        for r in recs[:8]:
            lines.append(f"- **{r['action']}** → `{r['target']}` — {r['rationale']}")
        return "\n".join(lines)


if __name__ == "__main__":
    import uuid
    from datetime import datetime

    from mentisrex.hypothesis.models import HypothesisRecord
    from mentisrex.research.models import ExperimentRecord, ValidationReport, Verdict

    kg = KnowledgeGraph(":memory:")
    hyp = HypothesisStore(":memory:")
    res = ResearchStore(":memory:")

    def _h(id_, cat, conf, status="Active") -> HypothesisRecord:
        now = datetime.now(UTC)
        return HypothesisRecord(
            id=id_,
            parent_papers=[f"paper:{id_}"],
            research_category=cat,
            economic_intuition="reason " * 30,
            testable_statement="IF x THEN y",
            expected_behavior="",
            asset_classes=["equities"],
            required_datasets=["crsp"],
            required_features=["mom_12m"],
            holding_period="1_month",
            expected_risks=[],
            confidence_score=conf,
            assumptions=[],
            dependencies=[],
            validation_requirements=[],
            similar_to=[],
            status=status,
            version=1,
            created_at=now,
            updated_at=now,
            researcher="llm",
            generation_method="llm",
        )

    def _exp(hid, verdict, sharpe, feats, reasons) -> ExperimentRecord:
        rep = ValidationReport(
            verdict=verdict,
            reasons=reasons,
            is_sharpe=sharpe + 0.2,
            oos_sharpe=sharpe,
            oos_return=0.1,
            oos_max_drawdown=-0.1,
            oos_trades=50,
            n_trials=5,
            adjusted_pvalue=0.02 if verdict == Verdict.ACCEPT else 0.4,
        )
        return ExperimentRecord(
            id=str(uuid.uuid4()),
            hypothesis_id=hid,
            researcher="llm",
            created_at=datetime.now(UTC),
            dataset_version="crsp_v1",
            strategy_name="s",
            strategy_version=1,
            features_used=feats,
            params={},
            report=rep,
        )

    hyp.insert(_h("h_win", "factor_anomaly", 0.85))
    hyp.insert(_h("h_lose", "sentiment", 0.4))
    # productive category
    for _ in range(3):
        res.record_experiment(_exp("h_win", Verdict.ACCEPT, 1.2, ["mom_12m"], ["passed"]))
    # consistently failing category
    for _ in range(4):
        res.record_experiment(
            _exp(
                "h_lose",
                Verdict.REJECT,
                -0.1,
                ["sent_news"],
                ["oos sharpe below floor", "significance: p>alpha"],
            )
        )

    from mentisrex.paper.outcomes import PaperOutcome, PaperOutcomeStore

    paper = PaperOutcomeStore(":memory:")
    # h_win passed validation but fails live → validation false positive.
    paper.record(
        "h_win",
        "mom_strat",
        PaperOutcome.FAILED,
        regime="bear",
        paper_sharpe=-0.3,
        backtest_sharpe=1.2,
    )

    intel = ResearchIntelligence(kg=kg, hypotheses=hyp, research=res, paper=paper)
    meta = intel.meta_analysis()
    cats = {c["category"]: c["verdict"] for c in meta["category_performance"]}
    assert cats["sentiment"] == "consistently_fails", cats
    assert cats["factor_anomaly"] == "productive", cats

    guards = intel.statistical_test_effectiveness()
    assert any(g["guard"].startswith("oos sharpe") for g in guards), guards

    recs = intel.recommendations()
    assert any(r["type"] == "retire" and r["target"] == "sentiment" for r in recs)
    assert all("evidence" in r for r in recs)
    assert any(r["action"] == "retire_strategy" for r in recs), "failed paper outcome -> retire"

    se = intel.self_evaluation()
    assert se["decision_signal_lift"] > 0, se  # high-confidence hypo accepted more

    ptr = meta["paper_trading_reliability"]
    assert ptr["false_positive_rate"] == 1.0, ptr  # 1/1 decided failed
    assert se["validation_false_positive_rate"] == 1.0, se
    regime = meta["regime_sensitivity"]["by_paper_regime"]
    assert any(r["regime"] == "bear" and r["failure_rate"] == 1.0 for r in regime), regime

    rep = intel.report("monthly")
    assert "# Monthly Research Intelligence Report" in rep["markdown"]
    print(
        "intelligence self-check ok:",
        cats,
        "| recs:",
        len(recs),
        "| fp_rate:",
        ptr["false_positive_rate"],
    )

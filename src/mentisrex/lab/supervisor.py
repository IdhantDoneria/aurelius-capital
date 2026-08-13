"""Laboratory Supervisor — coordinates the 13-step autonomous research cycle.

The Supervisor is the ONLY component that talks to every subsystem. Each step
reads/writes a shared per-cycle state dict; no subsystem calls another directly.
Steps are ordered, dependency-gated, retried on failure, and journalled. A step
that lacks a real input (no paper source, no market-data provider) raises
StepSkipped with a concrete reason and unblock hint — it never fabricates data.

Failure recovery: a failed non-critical step is recorded and the cycle CONTINUES
(a validation step whose experiments never ran simply skips). Each cycle is
independent, so an external supervisor (systemd/cron) restarting the process
resumes cleanly on the next cycle.

Redesigns nothing — pure integration of existing frameworks.
"""

from __future__ import annotations

import duckdb
import time
import uuid
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mentisrex.backtesting.data.feed import BarData
from mentisrex.core.logging import get_logger
from mentisrex.director.director import Decision, ResearchDirector
from mentisrex.hypothesis.deduplication import DuplicateStatus, check_duplicates
from mentisrex.hypothesis.generator import LLMClient, generate
from mentisrex.hypothesis.models import HypothesisRecord
from mentisrex.hypothesis.store import HypothesisStore
from mentisrex.intelligence.engine import ResearchIntelligence
from mentisrex.knowledge.graph import KnowledgeGraph
from mentisrex.lab.journal import LabJournal
from mentisrex.literature.enrichment import enrich
from mentisrex.literature.models import Paper
from mentisrex.literature.store import LiteratureStore
from mentisrex.paper.outcomes import PaperOutcomeStore
from mentisrex.research.models import Hypothesis, ValidationCriteria
from mentisrex.research.runner import ResearchRunner
from mentisrex.research.store import ResearchStore
from mentisrex.research.templates import MeanReversionStrategy, MomentumStrategy

logger = get_logger(__name__)

# Provider seams. Left None by default so the Laboratory runs honestly on an
# empty install — the dependent steps skip with a reason instead of faking data.
PaperSource = Callable[[], list[Paper]]  # e.g. an arXiv/SSRN fetcher
BarsProvider = Callable[[dict], Sequence[BarData]]  # spec -> market bars
Notifier = Callable[..., None]

_CATEGORY_STRATEGY = {
    "mean_reversion": (MeanReversionStrategy, {"lookback": 20}),
    "statistical_arbitrage": (MeanReversionStrategy, {"lookback": 20}),
}
_DEFAULT_STRATEGY = (MomentumStrategy, {"lookback": 20})


class StepSkipped(Exception):  # noqa: N818 — a skip signal, not an error condition
    """Raised by a step that cannot run for a concrete, stated reason."""


@dataclass
class JobResult:
    step: str
    status: str  # ok | skipped | failed
    attempts: int
    duration_ms: float
    summary: dict = field(default_factory=dict)
    error: str | None = None
    reason: str | None = None


class Supervisor:
    def __init__(
        self,
        *,
        literature: LiteratureStore | None = None,
        hypotheses: HypothesisStore | None = None,
        research: ResearchStore | None = None,
        kg: KnowledgeGraph | None = None,
        paper: PaperOutcomeStore | None = None,
        journal: LabJournal | None = None,
        llm: LLMClient | None = None,
        paper_source: PaperSource | None = None,
        bars_provider: BarsProvider | None = None,
        notifier: Notifier | None = None,
        cycle_budget_min: float = 240.0,  # compute budget per cycle (experiment-minutes)
        max_new_hypotheses: int = 20,
        report_periods: tuple[str, ...] = ("daily",),
        reports_dir: str = "./data/reports",
        retries: int = 2,
    ) -> None:
        from mentisrex.infrastructure.config.settings import get_settings

        s = get_settings()
        self.lit = literature or LiteratureStore()
        self.hyp = hypotheses or HypothesisStore()
        self.research = research or ResearchStore()
        self.kg = kg or KnowledgeGraph(s.knowledge_graph_path)
        self.paper = paper or PaperOutcomeStore(s.paper_outcomes_path)
        self.journal = journal or LabJournal()
        self.director = ResearchDirector(kg=self.kg, hypotheses=self.hyp, research=self.research)
        self.intel = ResearchIntelligence(
            kg=self.kg, hypotheses=self.hyp, research=self.research, paper=self.paper
        )
        self.runner = ResearchRunner(self.research, ValidationCriteria())

        self.llm = llm
        self.paper_source = paper_source
        self.bars_provider = bars_provider
        self.notify: Notifier = notifier or self._default_notify
        self.cycle_budget_min = cycle_budget_min
        self.max_new_hypotheses = max_new_hypotheses
        self.report_periods = report_periods
        self.reports_dir = Path(reports_dir)
        self.retries = retries
        self.last_cycle: dict | None = None

    def _default_notify(self, level: str, event: str, **data: Any) -> None:
        (logger.error if level == "error" else logger.info)(event, level=level, **data)

    # ── Cycle driver ────────────────────────────────────────────────────────────

    def _steps(self) -> list[tuple[str, Callable, list[str]]]:
        # (name, method, hard-dependency step names)
        return [
            ("discover_literature", self._s01_discover, []),
            ("update_literature", self._s02_update_literature, []),
            ("generate_hypotheses", self._s03_generate, []),
            ("compare_knowledge_graph", self._s04_compare_kg, ["generate_hypotheses"]),
            ("remove_duplicates", self._s05_dedup, ["generate_hypotheses"]),
            ("prioritize", self._s06_prioritize, []),
            ("create_experiment_specs", self._s07_specs, ["prioritize"]),
            ("execute_experiments", self._s08_execute, ["create_experiment_specs"]),
            ("statistical_validation", self._s09_validate, ["execute_experiments"]),
            ("store_results", self._s10_store, ["execute_experiments"]),
            ("update_knowledge_graph", self._s11_update_kg, []),
            ("recommendations", self._s12_recommendations, []),
            ("reports", self._s13_reports, []),
        ]

    def run_cycle(self) -> dict:
        cycle_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:6]
        self.journal.log("cycle_start", cycle_id)
        self.notify("info", "lab_cycle_start", cycle_id=cycle_id)

        state: dict[str, Any] = {}
        results: dict[str, JobResult] = {}
        for name, fn, deps in self._steps():
            blocked = [d for d in deps if results.get(d) and results[d].status != "ok"]
            if blocked:
                jr = JobResult(
                    name,
                    "skipped",
                    0,
                    0.0,
                    reason=f"dependency {blocked[0]} was {results[blocked[0]].status}",
                )
                results[name] = jr
                self._journal_job(cycle_id, jr)
                continue
            results[name] = self._run_step(cycle_id, name, fn, state)

        tally = Counter(r.status for r in results.values())
        summary = {
            "cycle_id": cycle_id,
            "finished_at": datetime.now(UTC).isoformat(),
            "ok": tally.get("ok", 0),
            "skipped": tally.get("skipped", 0),
            "failed": tally.get("failed", 0),
            "steps": {
                n: {"status": r.status, "summary": r.summary, "reason": r.reason, "error": r.error}
                for n, r in results.items()
            },
        }
        self.journal.log(
            "cycle_complete",
            cycle_id,
            ok=summary["ok"],
            skipped=summary["skipped"],
            failed=summary["failed"],
        )
        level = "error" if summary["failed"] else "info"
        self.notify(
            level,
            "lab_cycle_complete",
            cycle_id=cycle_id,
            ok=summary["ok"],
            skipped=summary["skipped"],
            failed=summary["failed"],
        )
        self.last_cycle = summary
        return summary

    def run_forever(self, interval_s: float = 3600.0, max_cycles: int | None = None) -> None:
        """Continuous operation. External process supervision handles process death;
        each cycle is independent so a restart resumes on the next tick."""
        n = 0
        while max_cycles is None or n < max_cycles:
            try:
                self.run_cycle()
            except Exception as exc:  # a cycle must never kill the loop
                logger.exception("lab_cycle_crashed", error=str(exc))
                self.notify("error", "lab_cycle_crashed", error=str(exc))
            n += 1
            if max_cycles is not None and n >= max_cycles:
                break
            time.sleep(interval_s)

    def _run_step(self, cycle_id: str, name: str, fn: Callable, state: dict) -> JobResult:
        attempts = 0
        t0 = time.perf_counter()
        while True:
            attempts += 1
            try:
                summary = fn(state) or {}
                jr = JobResult(
                    name, "ok", attempts, (time.perf_counter() - t0) * 1000, summary=summary
                )
                self._journal_job(cycle_id, jr)
                return jr
            except StepSkipped as skip:
                jr = JobResult(
                    name, "skipped", attempts, (time.perf_counter() - t0) * 1000, reason=str(skip)
                )
                self._journal_job(cycle_id, jr)
                return jr
            except Exception as exc:  # retryable
                if attempts <= self.retries:
                    logger.warning("lab_step_retry", step=name, attempt=attempts, error=str(exc))
                    time.sleep(min(2 ** (attempts - 1) * 0.05, 1.0))  # capped backoff
                    continue
                jr = JobResult(
                    name, "failed", attempts, (time.perf_counter() - t0) * 1000, error=str(exc)
                )
                self._journal_job(cycle_id, jr)
                self.notify("error", "lab_step_failed", step=name, error=str(exc))
                return jr

    def _journal_job(self, cycle_id: str, jr: JobResult) -> None:
        self.journal.log(
            "job",
            cycle_id,
            step=jr.step,
            status=jr.status,
            attempts=jr.attempts,
            duration_ms=round(jr.duration_ms, 1),
            summary=jr.summary,
            reason=jr.reason,
            error=jr.error,
        )

    # ── Steps 1-13 ──────────────────────────────────────────────────────────────

    def _s01_discover(self, state: dict) -> dict:
        if self.paper_source is None:
            raise StepSkipped(
                "no paper discovery source wired. Inject paper_source: Callable[[], "
                "list[Paper]] (e.g. an arXiv/SSRN fetcher). Operating on already-stored "
                "literature this cycle."
            )
        papers = list(self.paper_source())
        state["discovered"] = papers
        return {"discovered": len(papers)}

    def _s02_update_literature(self, state: dict) -> dict:
        inserted = 0
        for p in state.get("discovered", []):
            if self.lit.upsert(p):
                inserted += 1
        enriched = 0
        if self.llm is not None:
            for p in self.lit.pending_enrichment(limit=50):
                self.lit.upsert(enrich(p, self.llm))
                enriched += 1
        state["papers"] = self.lit.all_papers(limit=self.max_new_hypotheses)
        return {"inserted": inserted, "enriched": enriched, "enrichment_skipped": self.llm is None}

    def _s03_generate(self, state: dict) -> dict:
        papers = state.get("papers") or self.lit.all_papers(limit=self.max_new_hypotheses)
        candidates: list[HypothesisRecord] = []
        for p in papers:
            candidates.extend(generate(p, self.llm))
            if len(candidates) >= self.max_new_hypotheses:
                break
        state["candidates"] = candidates[: self.max_new_hypotheses]
        return {
            "papers_considered": len(papers),
            "generated": len(state["candidates"]),
            "llm": self.llm is not None,
        }

    def _s04_compare_kg(self, state: dict) -> dict:
        related = 0
        for h in state.get("candidates", []):
            try:
                hits = self.kg.search(h.testable_statement, node_type="hypothesis", limit=3)
            except duckdb.Error:
                hits = []
            if hits:
                related += 1
        return {"candidates": len(state.get("candidates", [])), "with_kg_matches": related}

    def _s05_dedup(self, state: dict) -> dict:
        existing = self.hyp.all_statements()
        inserted, dropped = [], 0
        for h in state.get("candidates", []):
            res = check_duplicates(h, existing)
            if res.status == DuplicateStatus.DUPLICATE:
                dropped += 1
                continue
            h.similar_to = res.similar_ids
            if self.hyp.insert(h):  # fires KG hook internally
                inserted.append(h.id)
                existing.append((h.id, h.testable_statement))  # dedup within the batch too
        state["inserted"] = inserted
        return {"inserted": len(inserted), "duplicates_dropped": dropped}

    def _s06_prioritize(self, state: dict) -> dict:
        ranked = self.director.prioritize()
        actionable = [
            r for r in ranked if r.decision in (Decision.RESEARCH_NOW.value, Decision.DELAY.value)
        ]
        # Resource management: fill the cycle compute budget greedily by priority.
        queue, spent = [], 0.0  # type: ignore
        for r in actionable:
            cost = float(r.resources["runtime_min"])
            if spent + cost > self.cycle_budget_min and queue:
                break
            queue.append(
                {"hypothesis_id": r.hypothesis_id, "priority": r.overall, "runtime_min": cost}
            )
            spent += cost
        state["queue"] = queue
        return {"ranked": len(ranked), "queued": len(queue), "budget_used_min": round(spent, 1)}

    def _s07_specs(self, state: dict) -> dict:
        specs = []
        for item in state.get("queue", []):
            h = self.hyp.get(item["hypothesis_id"])
            if h is None:
                continue
            strat, params = _CATEGORY_STRATEGY.get(h.research_category, _DEFAULT_STRATEGY)
            specs.append(
                {
                    "hypothesis_id": h.id,
                    "statement": h.testable_statement,
                    "rationale": h.economic_intuition,
                    "researcher": h.researcher,
                    "strategy": strat.__name__,
                    "params": params,
                    "features_used": h.required_features,
                    "symbols": ["AAA", "BBB"],  # provider maps hypothesis universe -> symbols
                }
            )
        state["specs"] = specs
        return {"specs": len(specs)}

    def _s08_execute(self, state: dict) -> dict:
        if self.bars_provider is None:
            raise StepSkipped(
                "no market-data provider wired. Inject bars_provider: Callable[[spec], "
                "Sequence[BarData]] so experiments run on real bars. Refusing to "
                "backtest on synthetic data by default — results would not be reproducible "
                "research."
            )
        verdicts: Counter[str] = Counter()
        reports = []
        for spec in state.get("specs", []):
            bars = self.bars_provider(spec)
            if not bars:
                continue
            strat_cls = {
                "MomentumStrategy": MomentumStrategy,
                "MeanReversionStrategy": MeanReversionStrategy,
            }[spec["strategy"]]
            hyp = Hypothesis(
                id=spec["hypothesis_id"],
                statement=spec["statement"],
                rationale=spec["rationale"],
                researcher=spec["researcher"],
                created_at=datetime.now(UTC),
            )
            report = self.runner.investigate(
                hyp,
                lambda p, c=strat_cls: c(**p),
                spec["params"],
                bars,
                features_used=spec["features_used"],
            )
            verdicts[report.verdict.value] += 1
            reports.append(
                {
                    "hypothesis_id": spec["hypothesis_id"],
                    "verdict": report.verdict.value,
                    "oos_sharpe": round(report.oos_sharpe, 3),
                }
            )
        state["reports"] = reports
        return {"executed": len(reports), "verdicts": dict(verdicts)}

    def _s09_validate(self, state: dict) -> dict:
        # Validation runs inside investigate (evaluate()); this step summarises it.
        verdicts = Counter(r["verdict"] for r in state.get("reports", []))
        return {"validated": sum(verdicts.values()), "verdicts": dict(verdicts)}

    def _s10_store(self, state: dict) -> dict:
        # record_experiment already persisted each result (and fired KG hooks).
        return {"stored": len(state.get("reports", []))}

    def _s11_update_kg(self, state: dict) -> dict:
        from mentisrex.knowledge.ingest import ingest_all

        try:
            ingested = ingest_all(self.kg)  # full resync from every store
        except duckdb.Error as exc:
            ingested = {"error": str(exc)}
        stats = self.director._safe(self.kg.stats)
        node_total = (
            sum(t.get("count", 0) for t in stats.get("nodes_by_type", []))
            if isinstance(stats, dict)
            else 0
        )
        return {"ingested": ingested, "kg_nodes": node_total}

    def _s12_recommendations(self, state: dict) -> dict:
        recs = self.intel.recommendations()
        state["recommendations"] = recs
        return {"recommendations": len(recs), "by_type": dict(Counter(r["type"] for r in recs))}

    def _s13_reports(self, state: dict) -> dict:
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        written = []
        for period in self.report_periods:
            rep = self.intel.report(period)
            fname = self.reports_dir / f"{period}-{datetime.now(UTC).date()}.md"
            fname.write_text(rep["markdown"])
            written.append(str(fname))
        return {"reports_written": written}


if __name__ == "__main__":
    import tempfile
    from datetime import date

    from mentisrex.research.runner import synth_bars

    tmp = Path(tempfile.mkdtemp())

    def _paper_source() -> list[Paper]:
        return [
            Paper(
                id="p_lab_1",
                source="arxiv",
                source_id="2601.00001",
                title="Cross-sectional momentum in equities",
                authors=["A. Researcher"],
                published_at=date(2026, 1, 1),
                abstract="Momentum persists over 3-12 month horizons in equity cross-sections.",
                url="http://example.com",
                research_category="factor_anomaly",
                asset_classes=["equities"],
                enriched=True,
            )
        ]

    _bars = synth_bars(["AAA", "BBB"], days=220)

    sup = Supervisor(
        literature=LiteratureStore(":memory:"),
        hypotheses=HypothesisStore(":memory:"),
        research=ResearchStore(":memory:"),
        kg=KnowledgeGraph(":memory:"),
        paper=PaperOutcomeStore(":memory:"),
        journal=LabJournal(tmp / "j.jsonl"),
        paper_source=_paper_source,
        bars_provider=lambda spec: _bars,
        report_periods=("daily",),
        reports_dir=str(tmp / "reports"),
    )
    summary = sup.run_cycle()
    assert summary["failed"] == 0, summary
    steps = summary["steps"]
    assert steps["discover_literature"]["status"] == "ok", steps["discover_literature"]
    assert steps["remove_duplicates"]["summary"]["inserted"] >= 1, steps["remove_duplicates"]
    assert steps["execute_experiments"]["status"] == "ok", steps["execute_experiments"]
    assert steps["execute_experiments"]["summary"]["executed"] >= 1
    # audit trail complete
    assert sup.journal.read(cycle_id=summary["cycle_id"], kind="job")
    print("supervisor self-check ok:", {k: v["status"] for k, v in steps.items()})

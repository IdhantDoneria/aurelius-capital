"""Ingestion adapters — project existing DuckDB stores into the KnowledgeGraph.

Each source function is idempotent: re-running it upserts without duplication.
Call ingest_all() to sync everything. Designed to run on demand (POST /kg/ingest)
or as a scheduled job after any framework produces new output.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import duckdb

from mentisrex.core.logging import get_logger
from mentisrex.knowledge.graph import KnowledgeGraph

if TYPE_CHECKING:
    from mentisrex.hypothesis.models import HypothesisRecord
    from mentisrex.literature.models import Paper
    from mentisrex.research.models import ExperimentRecord

logger = get_logger(__name__)


def _open_ro(db_path: str) -> duckdb.DuckDBPyConnection:
    if not Path(db_path).exists():
        raise FileNotFoundError(db_path)
    return duckdb.connect(db_path, read_only=True)


def _parse_list(val: Any) -> list[str]:
    """Normalise stored lists: JSON array string, comma-separated, or Python list."""
    if not val:
        return []
    if isinstance(val, list):
        return [str(v).strip() for v in val if v]
    s = str(val).strip()
    if s.startswith("["):
        try:
            return [str(v).strip() for v in json.loads(s) if v]
        except json.JSONDecodeError:
            pass
    return [x.strip() for x in s.split(",") if x.strip()]


def _slug(text: str, maxlen: int = 80) -> str:
    return text.lower().replace(" ", "_")[:maxlen]


def ingest_literature(kg: KnowledgeGraph, db_path: str = "./data/literature.duckdb") -> int:
    with _open_ro(db_path) as conn:
        cols = [d[0] for d in conn.execute("SELECT * FROM papers LIMIT 0").description]
        rows = [
            dict(zip(cols, r, strict=False))
            for r in conn.execute("SELECT * FROM papers").fetchall()
        ]

    count = 0
    for p in rows:
        text = " ".join(
            filter(None, [p.get("abstract"), p.get("main_conclusions"), p.get("methodology")])
        )
        kg.upsert_node(
            node_id=p["id"],
            node_type="paper",
            label=(p.get("title") or p["id"])[:200],
            properties=p,
            text_corpus=text,
            change_reason="literature_ingest",
        )
        for author in _parse_list(p.get("authors")):
            aid = f"author:{_slug(author)}"
            kg.upsert_node(aid, "author", author, change_reason="literature_ingest")
            kg.upsert_edge(p["id"], aid, "authored_by")
        for ds in _parse_list(p.get("datasets")):
            did = f"dataset:{_slug(ds)}"
            kg.upsert_node(did, "dataset", ds, change_reason="literature_ingest")
            kg.upsert_edge(p["id"], did, "mentions")
        if p.get("research_category"):
            rc_id = f"research_category:{_slug(p['research_category'])}"
            kg.upsert_node(
                rc_id,
                "research_category",
                p["research_category"],
                change_reason="literature_ingest",
            )
            kg.upsert_edge(p["id"], rc_id, "categorized_as")
        count += 1

    logger.info("kg_ingest_literature", count=count)
    return count


def ingest_hypotheses(kg: KnowledgeGraph, db_path: str = "./data/hypothesis.duckdb") -> int:
    """Ingest from HypothesisStore (the detailed hypothesis framework store)."""
    try:
        with _open_ro(db_path) as conn:
            cols = [d[0] for d in conn.execute("SELECT * FROM hypotheses LIMIT 0").description]
            rows = [
                dict(zip(cols, r, strict=False))
                for r in conn.execute("SELECT * FROM hypotheses").fetchall()
            ]
    except (FileNotFoundError, duckdb.IOException):
        logger.warning("kg_source_missing", source="hypotheses", path=db_path)
        return 0

    count = 0
    for h in rows:
        text = " ".join(
            filter(
                None,
                [
                    h.get("testable_statement"),
                    h.get("economic_intuition"),
                    h.get("expected_behavior"),
                ],
            )
        )
        kg.upsert_node(
            node_id=h["id"],
            node_type="hypothesis",
            label=(h.get("testable_statement") or h["id"])[:200],
            properties=h,
            text_corpus=text,
            change_reason="hypothesis_ingest",
        )
        for paper_id in _parse_list(h.get("parent_papers")):
            kg.upsert_edge(paper_id, h["id"], "proposes")
        for ds in _parse_list(h.get("required_datasets")):
            did = f"dataset:{_slug(ds)}"
            kg.upsert_node(did, "dataset", ds, change_reason="hypothesis_ingest")
            kg.upsert_edge(h["id"], did, "uses_dataset")
        for feat in _parse_list(h.get("required_features")):
            fid = f"feature:{_slug(feat)}"
            kg.upsert_node(fid, "feature", feat, change_reason="hypothesis_ingest")
            kg.upsert_edge(h["id"], fid, "uses_feature")
        for sim_id in _parse_list(h.get("similar_to")):
            kg.upsert_edge(h["id"], sim_id, "similar_to")
        if h.get("research_category"):
            rc_id = f"research_category:{_slug(h['research_category'])}"
            kg.upsert_node(rc_id, "research_category", h["research_category"])
            kg.upsert_edge(h["id"], rc_id, "categorized_as")
        count += 1

    logger.info("kg_ingest_hypotheses", count=count)
    return count


def ingest_experiments(kg: KnowledgeGraph, db_path: str = "./data/research.duckdb") -> int:
    """Ingest from ResearchStore: hypotheses (simple) + experiments + inline validation results."""
    try:
        conn = _open_ro(db_path)
    except (FileNotFoundError, duckdb.IOException):
        logger.warning("kg_source_missing", source="experiments", path=db_path)
        return 0

    with conn:
        exp_cols = [d[0] for d in conn.execute("SELECT * FROM experiments LIMIT 0").description]
        experiments = [
            dict(zip(exp_cols, r, strict=False))
            for r in conn.execute("SELECT * FROM experiments").fetchall()
        ]
        hyp_cols = [d[0] for d in conn.execute("SELECT * FROM hypotheses LIMIT 0").description]
        research_hypotheses = [
            dict(zip(hyp_cols, r, strict=False))
            for r in conn.execute("SELECT * FROM hypotheses").fetchall()
        ]

    # ResearchStore hypotheses (simpler model — don't overwrite if HypothesisStore already ingested)
    for h in research_hypotheses:
        existing = kg.get_node(h["id"])
        if not existing:
            kg.upsert_node(
                node_id=h["id"],
                node_type="hypothesis",
                label=(h.get("statement") or h["id"])[:200],
                properties=h,
                text_corpus=h.get("rationale", ""),
                change_reason="research_ingest",
            )

    count = 0
    for e in experiments:
        verdict = e.get("verdict", "unknown")
        kg.upsert_node(
            node_id=e["id"],
            node_type="experiment",
            label=f"Experiment[{verdict}]:{e.get('strategy_name', e['id'][:8])}",
            properties=e,
            text_corpus=f"{e.get('strategy_name', '')} {e.get('reasons', '')}",
            change_reason="experiment_ingest",
        )
        if e.get("hypothesis_id"):
            kg.upsert_edge(e["hypothesis_id"], e["id"], "generates")

        for feat in _parse_list(e.get("features_used")):
            fid = f"feature:{_slug(feat)}"
            kg.upsert_node(fid, "feature", feat, change_reason="experiment_ingest")
            kg.upsert_edge(e["id"], fid, "depends_on")

        # Validation node synthesised from inline experiment fields
        val_id = f"validation:{e['id']}"
        val_props = {
            k: e[k]
            for k in (
                "verdict",
                "oos_sharpe",
                "oos_return",
                "oos_max_drawdown",
                "adjusted_pvalue",
                "n_trials",
                "reasons",
                "is_sharpe",
            )
            if k in e and e[k] is not None
        }
        strat = e.get("strategy_name", e["id"][:8])
        kg.upsert_node(
            node_id=val_id,
            node_type="validation_report",
            label=f"Validation[{verdict}]:{strat}"[:200],
            properties=val_props,
            text_corpus=str(e.get("reasons", "")),
            change_reason="experiment_ingest",
        )
        kg.upsert_edge(e["id"], val_id, "produces")
        if e.get("hypothesis_id"):
            kg.upsert_edge(val_id, e["hypothesis_id"], "evaluates")

        count += 1

    logger.info("kg_ingest_experiments", count=count)
    return count


def ingest_all(
    kg: KnowledgeGraph,
    literature_path: str = "./data/literature.duckdb",
    hypothesis_path: str = "./data/hypothesis.duckdb",
    research_path: str = "./data/research.duckdb",
) -> dict[str, int]:
    """Sync all sources into the KG. Safe to call repeatedly — all ops are idempotent."""
    results: dict[str, int] = {}
    for name, fn, path in [
        ("literature", ingest_literature, literature_path),
        ("hypotheses", ingest_hypotheses, hypothesis_path),
        ("experiments", ingest_experiments, research_path),
    ]:
        try:
            results[name] = fn(kg, path)
        except Exception as exc:
            logger.error("kg_ingest_error", source=name, error=str(exc)[:200])
            results[name] = -1

    kg.rebuild_fts()
    results["embedded"] = kg.embed_all_nodes()
    logger.info("kg_ingest_all_complete", results=results)
    return results


# ── Single-entity ingest (used by real-time hooks) ────────────────────────────


def _ingest_paper_obj(kg: KnowledgeGraph, paper: Paper) -> None:
    text = " ".join(
        filter(
            None,
            [
                getattr(paper, "abstract", ""),
                getattr(paper, "main_conclusions", ""),
                getattr(paper, "methodology", ""),
            ],
        )
    )
    props: dict[str, Any] = {
        "source": paper.source,
        "source_id": paper.source_id,
        "title": paper.title,
        "authors": paper.authors,
        "published_at": str(paper.published_at) if paper.published_at else None,
        "abstract": paper.abstract,
        "url": paper.url,
        "keywords": paper.keywords,
        "asset_classes": paper.asset_classes,
        "research_category": paper.research_category,
        "methodology": paper.methodology,
        "datasets": paper.datasets,
        "factors_studied": paper.factors_studied,
        "statistical_techniques": paper.statistical_techniques,
        "main_conclusions": paper.main_conclusions,
        "limitations": paper.limitations,
        "enriched": paper.enriched,
    }
    kg.upsert_node(
        node_id=paper.id,
        node_type="paper",
        label=(paper.title or paper.id)[:200],
        properties=props,
        text_corpus=text,
        change_reason="hook",
    )
    for author in paper.authors or []:
        aid = f"author:{_slug(author)}"
        kg.upsert_node(aid, "author", author, change_reason="hook")
        kg.upsert_edge(paper.id, aid, "authored_by")
    for ds in paper.datasets or []:
        did = f"dataset:{_slug(ds)}"
        kg.upsert_node(did, "dataset", ds, change_reason="hook")
        kg.upsert_edge(paper.id, did, "mentions")
    if paper.research_category:
        rc_id = f"research_category:{_slug(paper.research_category)}"
        kg.upsert_node(rc_id, "research_category", paper.research_category)
        kg.upsert_edge(paper.id, rc_id, "categorized_as")


def _ingest_hypothesis_obj(kg: KnowledgeGraph, h: HypothesisRecord) -> None:
    text = " ".join(
        filter(
            None,
            [
                getattr(h, "testable_statement", ""),
                getattr(h, "economic_intuition", ""),
                getattr(h, "expected_behavior", ""),
            ],
        )
    )
    kg.upsert_node(
        node_id=h.id,
        node_type="hypothesis",
        label=(h.testable_statement or h.id)[:200],
        properties={
            "research_category": h.research_category,
            "status": h.status,
            "confidence_score": h.confidence_score,
            "testable_statement": h.testable_statement,
            "economic_intuition": h.economic_intuition,
            "expected_behavior": h.expected_behavior,
            "asset_classes": h.asset_classes,
            "required_datasets": h.required_datasets,
            "required_features": h.required_features,
            "holding_period": h.holding_period,
            "expected_risks": h.expected_risks,
            "assumptions": h.assumptions,
            "similar_to": h.similar_to,
            "rejection_reason": h.rejection_reason,
            "version": h.version,
            "researcher": h.researcher,
        },
        text_corpus=text,
        change_reason="hook",
    )
    for paper_id in h.parent_papers or []:
        kg.upsert_edge(paper_id, h.id, "proposes")
    for ds in h.required_datasets or []:
        did = f"dataset:{_slug(ds)}"
        kg.upsert_node(did, "dataset", ds, change_reason="hook")
        kg.upsert_edge(h.id, did, "uses_dataset")
    for feat in h.required_features or []:
        fid = f"feature:{_slug(feat)}"
        kg.upsert_node(fid, "feature", feat, change_reason="hook")
        kg.upsert_edge(h.id, fid, "uses_feature")
    for sim_id in h.similar_to or []:
        kg.upsert_edge(h.id, sim_id, "similar_to")
    if h.research_category:
        rc_id = f"research_category:{_slug(h.research_category)}"
        kg.upsert_node(rc_id, "research_category", h.research_category)
        kg.upsert_edge(h.id, rc_id, "categorized_as")


def _ingest_experiment_obj(kg: KnowledgeGraph, rec: ExperimentRecord) -> None:
    r = rec.report
    verdict = r.verdict.value
    kg.upsert_node(
        node_id=rec.id,
        node_type="experiment",
        label=f"Experiment[{verdict}]:{rec.strategy_name}",
        properties={
            "hypothesis_id": rec.hypothesis_id,
            "researcher": rec.researcher,
            "strategy_name": rec.strategy_name,
            "strategy_version": rec.strategy_version,
            "features_used": rec.features_used,
            "params": rec.params,
            "verdict": verdict,
            "reasons": r.reasons,
            "is_sharpe": r.is_sharpe,
            "oos_sharpe": r.oos_sharpe,
            "oos_return": r.oos_return,
            "oos_max_drawdown": r.oos_max_drawdown,
            "oos_trades": r.oos_trades,
            "n_trials": r.n_trials,
            "adjusted_pvalue": r.adjusted_pvalue,
            "dataset_version": rec.dataset_version,
        },
        text_corpus=f"{rec.strategy_name} {' '.join(r.reasons)}",
        change_reason="hook",
    )
    if rec.hypothesis_id:
        kg.upsert_edge(rec.hypothesis_id, rec.id, "generates")
    for feat in rec.features_used or []:
        fid = f"feature:{_slug(feat)}"
        kg.upsert_node(fid, "feature", feat, change_reason="hook")
        kg.upsert_edge(rec.id, fid, "depends_on")
    val_id = f"validation:{rec.id}"
    kg.upsert_node(
        node_id=val_id,
        node_type="validation_report",
        label=f"Validation[{verdict}]:{rec.strategy_name}"[:200],
        properties={
            "verdict": verdict,
            "reasons": r.reasons,
            "oos_sharpe": r.oos_sharpe,
            "oos_return": r.oos_return,
            "oos_max_drawdown": r.oos_max_drawdown,
            "adjusted_pvalue": r.adjusted_pvalue,
            "n_trials": r.n_trials,
            "is_sharpe": r.is_sharpe,
        },
        text_corpus=" ".join(r.reasons),
        change_reason="hook",
    )
    kg.upsert_edge(rec.id, val_id, "produces")
    if rec.hypothesis_id:
        kg.upsert_edge(val_id, rec.hypothesis_id, "evaluates")

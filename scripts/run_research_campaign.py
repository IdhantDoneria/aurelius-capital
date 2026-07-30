#!/usr/bin/env python
"""Phase 5-6 driver: derivative hypotheses + research-director ranking.

Operates existing frameworks over the papers ingested into CorpusStore this
campaign (those carrying a content_hash). Maps each corpus doc onto the
literature Paper contract the generator consumes, runs the existing
hypothesis generator + quality + dedup, persists to HypothesisStore, then
asks the ResearchDirector to score, decide, and rank.

    python scripts/run_research_campaign.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import duckdb

from aurelius.director.director import ResearchDirector
from aurelius.hypothesis.deduplication import DuplicateStatus, check_duplicates
from aurelius.hypothesis.generator import generate
from aurelius.hypothesis.quality import check_quality
from aurelius.hypothesis.store import HypothesisStore
from aurelius.knowledge.api import _get_kg
from aurelius.literature.models import Paper
from aurelius.research.store import ResearchStore

CORPUS_DB = "./data/corpus.duckdb"


def _corpus_papers() -> list[Paper]:
    """Adapt this campaign's corpus documents to the Paper contract."""
    conn = duckdb.connect(CORPUS_DB, read_only=True)
    rows = conn.execute(
        "SELECT id, title, authors, publication_date, abstract, classification, metadata "
        "FROM corpus_documents "
        "WHERE json_extract_string(metadata, '$.content_hash') IS NOT NULL "
        "ORDER BY created_at"
    ).fetchall()
    conn.close()

    papers = []
    for did, title, authors_j, pubdate, abstract, classif_j, meta_j in rows:
        meta = json.loads(meta_j) if meta_j else {}
        classif = json.loads(classif_j) if classif_j else {}
        authors = json.loads(authors_j) if authors_j else []
        asset_classes = classif.get("asset_class") or ["equities"]
        if isinstance(asset_classes, str):
            asset_classes = [asset_classes]
        papers.append(
            Paper(
                id=did,
                source="corpus",
                source_id=did,
                title=title,
                authors=authors,
                published_at=None,
                abstract=abstract or "",
                url=meta.get("source_file", ""),
                asset_classes=asset_classes,
                research_category=classif.get("research_domain", "") or "factor_anomaly",
                methodology=meta.get("methodology", ""),
                datasets=meta.get("datasets_mentioned", []),
                factors_studied=meta.get("features_mentioned", []),
                statistical_techniques=meta.get("statistical_tests", []),
                main_conclusions=abstract or "",
                enriched=True,
            )
        )
    return papers


def phase5(hyp_store: HypothesisStore) -> tuple[int, int]:
    papers = _corpus_papers()
    print(f"Phase 5 — generating hypotheses from {len(papers)} corpus paper(s)\n")
    existing = hyp_store.all_statements()
    inserted = rejected = 0
    for p in papers:
        cands = generate(p, llm=None, researcher="template")
        kept = 0
        for h in cands:
            qr = check_quality(h)
            if not qr.passed:
                h.status = "Rejected"
                h.rejection_reason = "; ".join(qr.reasons)
                hyp_store.insert(h)
                rejected += 1
                continue
            dr = check_duplicates(h, existing)
            if dr.status == DuplicateStatus.DUPLICATE:
                h.status = "Rejected"
                h.rejection_reason = f"duplicate of {dr.similar_ids[0]}"
                hyp_store.insert(h)
                rejected += 1
                continue
            if dr.status == DuplicateStatus.NEAR_DUPLICATE:
                h.similar_to = dr.similar_ids
            if hyp_store.insert(h):
                existing.append((h.id, h.testable_statement))
                inserted += 1
                kept += 1
        print(f"  {p.title[:50]:50s} → {len(cands)} cand, {kept} kept")
    print(f"\nPhase 5 done: inserted={inserted} rejected={rejected}")
    return inserted, rejected


def phase6(hyp_store: HypothesisStore) -> None:
    director = ResearchDirector(
        kg=_get_kg(), hypotheses=hyp_store, research=ResearchStore()
    )
    ranked = director.prioritize()
    print(f"\nPhase 6 — Research Director ranked queue ({len(ranked)} hypotheses)\n")
    print(f"{'rank':4s} {'overall':7s} {'decision':13s} {'category':16s} statement")
    for i, r in enumerate(ranked[:25], 1):
        print(f"{i:>4d} {r.overall:7.3f} {r.decision:13s} {r.category[:16]:16s} {r.statement[:60]}")
    # Top-5 explanations
    print("\nTop-5 score rationale:")
    for r in ranked[:5]:
        print(f"  [{r.overall:.3f}] {r.statement[:55]}")
        print(f"        {r.explanation}")


if __name__ == "__main__":
    store = HypothesisStore()
    phase5(store)
    phase6(store)

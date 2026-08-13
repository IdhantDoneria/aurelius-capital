"""Live-update hooks — called by stores immediately after a write.

Usage (in main.py, after KG singleton is created):
    from mentisrex.knowledge import hooks
    hooks.configure(kg_instance)

Stores call hooks.on_paper(), hooks.on_hypothesis(), hooks.on_experiment().
All hooks are no-ops until configure() is called — zero overhead in tests
that don't need the KG.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mentisrex.core.logging import get_logger

if TYPE_CHECKING:
    from mentisrex.hypothesis.models import HypothesisRecord
    from mentisrex.knowledge.graph import KnowledgeGraph
    from mentisrex.literature.models import Paper
    from mentisrex.research.models import ExperimentRecord

logger = get_logger(__name__)

_kg: KnowledgeGraph | None = None


def configure(kg: KnowledgeGraph) -> None:
    global _kg
    _kg = kg
    logger.info("kg_hooks_configured")


def is_configured() -> bool:
    return _kg is not None


def on_paper(paper: Paper) -> None:
    if _kg is None:
        return
    try:
        from mentisrex.knowledge.ingest import _ingest_paper_obj

        _ingest_paper_obj(_kg, paper)
        _kg.embed_node(paper.id)
    except Exception as exc:
        logger.warning("kg_hook_error", entity="paper", id=paper.id, error=str(exc)[:120])


def on_hypothesis(h: HypothesisRecord) -> None:
    if _kg is None:
        return
    try:
        from mentisrex.knowledge.ingest import _ingest_hypothesis_obj

        _ingest_hypothesis_obj(_kg, h)
        _kg.embed_node(h.id)
    except Exception as exc:
        logger.warning("kg_hook_error", entity="hypothesis", id=h.id, error=str(exc)[:120])


def on_experiment(rec: ExperimentRecord) -> None:
    if _kg is None:
        return
    try:
        from mentisrex.knowledge.ingest import _ingest_experiment_obj

        _ingest_experiment_obj(_kg, rec)
        _kg.embed_node(rec.id)
    except Exception as exc:
        logger.warning("kg_hook_error", entity="experiment", id=rec.id, error=str(exc)[:120])

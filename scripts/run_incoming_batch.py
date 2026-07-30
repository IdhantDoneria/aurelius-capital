#!/usr/bin/env python
"""Operate the existing ingestion pipeline over research_corpus/incoming.

Thin ops driver: constructs the same PipelineOrchestrator that main.py's
FolderWatcher uses, then runs every incoming file through it synchronously
and prints a compact per-paper receipt. Builds nothing new — invokes the
platform exactly as production would.

    python scripts/run_incoming_batch.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from aurelius.corpus.api import get_corpus_store
from aurelius.knowledge.api import _get_kg
from aurelius.operations.config import OperationsConfig
from aurelius.operations.models import JobStatus
from aurelius.operations.pipeline import PipelineOrchestrator

_SUPPORTED = {".pdf", ".txt", ".md", ".rst", ".tex", ".json"}


def main() -> None:
    cfg = OperationsConfig()
    cfg.ensure_dirs()
    pipeline = PipelineOrchestrator(cfg, get_corpus_store(), _get_kg())

    files = sorted(
        p for p in cfg.incoming.iterdir()
        if p.is_file() and p.suffix.lower() in _SUPPORTED
    )
    print(f"Discovered {len(files)} ingestible file(s) in {cfg.incoming}\n")

    ok = rejected = 0
    for path in files:
        job = pipeline.process_file(path)
        stages = " ".join(
            f"{s.stage}:{'ok' if s.status == 'success' else 'X'}" for s in job.stages
        )
        spec = job.experiment_spec or {}
        ready = spec.get("ready_to_run")
        missing = spec.get("missing_prerequisites", [])
        print(f"[{job.status.value.upper():9s}] {path.name}")
        print(f"    id={job.id[:8]} doc={job.corpus_doc_id} hash={(job.content_hash or '')[:12]}")
        print(f"    score={job.priority_score:.2f}  exp_ready={ready}  missing={missing}")
        if job.error:
            print(f"    ERROR: {job.error}")
        print(f"    stages: {stages}\n")
        if job.status == JobStatus.REJECTED:
            rejected += 1
        else:
            ok += 1

    print(f"Batch complete: {ok} completed, {rejected} rejected, {len(files)} total.")


if __name__ == "__main__":
    main()

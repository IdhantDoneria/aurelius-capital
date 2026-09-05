"""Autonomous research pipeline orchestrator.

Each paper moves through 9 stages. Failures are isolated — one paper's
failure never blocks others. Self-healing retries transient errors.
Journals every transition for resumability on restart.
"""

from __future__ import annotations

import shutil
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from mentisrex.core.logging import get_logger
from mentisrex.operations.config import OperationsConfig
from mentisrex.operations.extractor import compute_hash, extract_metadata, extract_text
from mentisrex.operations.healer import SelfHealer
from mentisrex.operations.journal import PipelineJournal
from mentisrex.operations.models import (
    IngestTimeoutError,
    JobStatus,
    PermanentIngestError,
    PipelineJob,
    StageResult,
)
from mentisrex.operations.planner import plan_experiment
from mentisrex.operations.scorer import score_paper

if TYPE_CHECKING:
    from mentisrex.corpus.store import CorpusStore
    from mentisrex.knowledge.graph import KnowledgeGraph

logger = get_logger(__name__)

_SUPPORTED_EXTENSIONS = {".pdf", ".txt", ".md", ".rst", ".tex", ".json"}


class PipelineOrchestrator:
    """Drives a single paper through all 9 pipeline stages."""

    def __init__(
        self,
        config: OperationsConfig,
        corpus_store: CorpusStore,
        kg: KnowledgeGraph,
    ) -> None:
        self._cfg = config
        self._corpus = corpus_store
        self._kg = kg
        self._journal = PipelineJournal(config.logs)
        self._healer = SelfHealer(config.max_retries, config.retry_delay_seconds)
        self._cfg.ensure_dirs()

    # ── public ───────────────────────────────────────────────────────────────

    def process_file(self, file_path: Path) -> PipelineJob:
        """Run all pipeline stages for one file. Returns final job state."""
        job = PipelineJob(
            original_filename=file_path.name,
            file_path=str(file_path),
            status=JobStatus.PROCESSING,
        )
        t0 = time.monotonic()
        deadline = t0 + self._cfg.per_file_timeout_seconds
        self._journal.record_job(job)

        stages = [
            ("validate", self._stage_validate),
            ("assign_id", self._stage_assign_id),
            ("move_to_processing", self._stage_move_to_processing),
            ("extract_metadata", self._stage_extract_metadata),
            ("classify", self._stage_classify),
            ("store_corpus", self._stage_store_corpus),
            ("update_kg", self._stage_update_kg),
            ("score", self._stage_score),
            ("plan_experiment", self._stage_plan_experiment),
            ("archive", self._stage_archive),
        ]

        for stage_name, stage_fn in stages:
            try:
                success = self._run_stage(job, stage_name, stage_fn, deadline)
            except PermanentIngestError as exc:
                logger.warning(
                    "permanent_ingest_failure", job_id=job.id, stage=stage_name, reason=str(exc)
                )
                self._reject(job, f"Permanent failure at '{stage_name}': {exc}")
                break
            except IngestTimeoutError as exc:
                logger.error(
                    "ingest_timeout",
                    job_id=job.id,
                    stage=stage_name,
                    timeout_seconds=self._cfg.per_file_timeout_seconds,
                    reason=str(exc),
                )
                self._reject(job, f"Timeout at '{stage_name}': {exc}")
                break
            if not success:
                if self._healer.needs_escalation(job):
                    self._reject(job, f"Stage '{stage_name}' failed after retries")
                    break
                # Non-fatal failure: log and continue
                logger.warning("stage_skipped_on_error", job_id=job.id, stage=stage_name)

        if job.status == JobStatus.PROCESSING:
            job.status = JobStatus.COMPLETED
        job.processing_seconds = time.monotonic() - t0
        job.updated_at = datetime.now(UTC)
        self._journal.record_job(job)
        self._save_metadata(job)
        return job

    def resume_incomplete(self) -> list[PipelineJob]:
        """On startup: find and reprocess any jobs stuck in PROCESSING state."""
        incomplete = self._journal.find_incomplete_jobs()
        results = []
        for raw in incomplete:
            src = Path(self._cfg.processing) / raw["original_filename"]
            if src.exists():
                logger.info("resuming_incomplete_job", filename=raw["original_filename"])
                results.append(self.process_file(src))
        return results

    # ── stages ───────────────────────────────────────────────────────────────

    def _stage_validate(self, job: PipelineJob) -> None:
        path = Path(job.file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        if path.suffix.lower() not in _SUPPORTED_EXTENSIONS:
            raise ValueError(f"Unsupported file type: {path.suffix}")
        if path.stat().st_size == 0:
            raise ValueError("Empty file")

    def _stage_assign_id(self, job: PipelineJob) -> None:
        job.content_hash = compute_hash(Path(job.file_path))
        # Idempotency: exact content-hash match (fuzzy search yields false positives)
        if self._corpus.document_exists_by_hash(job.content_hash):
            raise ValueError(f"Duplicate content hash {job.content_hash[:12]} already in corpus")

    def _stage_move_to_processing(self, job: PipelineJob) -> None:
        src = Path(job.file_path)
        dst = self._cfg.processing / src.name
        if src.resolve() != dst.resolve():
            shutil.move(str(src), str(dst))
        job.file_path = str(dst)

    def _stage_extract_metadata(self, job: PipelineJob) -> None:
        path = Path(job.file_path)
        raw_text = extract_text(path)  # raises PermanentIngestError on corrupt/unreadable input
        if not raw_text.strip():
            raise PermanentIngestError(
                "No text extractable from file (empty or unreadable content)"
            )
        meta = extract_metadata(path, raw_text)
        job.paper_metadata = meta
        # Save extracted text for audit
        extracted_path = self._cfg.extracted / f"{job.content_hash[:16]}.txt"
        extracted_path.write_text(raw_text[:50000], encoding="utf-8")

    def _stage_classify(self, job: PipelineJob) -> None:
        # Classification happens inside CorpusStore.add_document via CorpusClassifier
        # This stage just validates we have enough metadata to proceed
        meta = job.paper_metadata
        if not meta.get("title"):
            meta["title"] = Path(job.file_path).stem.replace("_", " ")
        if not meta.get("abstract"):
            meta["abstract"] = meta.get("results", "")[:300] or "No abstract available."

    def _stage_store_corpus(self, job: PipelineJob) -> None:
        meta = job.paper_metadata
        doc = self._corpus.add_document(
            title=meta["title"],
            content=meta.get("abstract", "") or meta.get("results", "") or meta["title"],
            doc_type="academic_paper",
            authors=meta.get("authors", []),
            publication_date=str(meta["year"]) if meta.get("year") else None,
            doi=meta.get("doi") or None,
            abstract=meta.get("abstract", ""),
            metadata={
                "methodology": meta.get("methodology", ""),
                "datasets_mentioned": meta.get("datasets_mentioned", []),
                "features_mentioned": meta.get("features_mentioned", []),
                "statistical_tests": meta.get("statistical_tests", []),
                "reference_count": meta.get("reference_count", 0),
                "arxiv_id": meta.get("arxiv_id", ""),
                "source_file": meta.get("source_file", ""),
                "content_hash": job.content_hash,
            },
        )
        job.corpus_doc_id = doc.id

    def _stage_update_kg(self, job: PipelineJob) -> None:
        meta = job.paper_metadata
        doc_id = job.corpus_doc_id

        # Paper node already created by CorpusStore KG sync; add author nodes + edges
        for author in meta.get("authors", []):
            author_id = f"author:{author.lower().replace(' ', '_')}"
            self._kg.upsert_node(
                node_id=author_id,
                node_type="author",
                label=author,
                properties={"name": author},
                text_corpus=author,
                change_reason="paper_ingestion",
            )
            self._kg.upsert_edge(doc_id, author_id, "authored_by")

        # Dataset nodes
        for dataset in meta.get("datasets_mentioned", []):
            ds_id = f"dataset:{dataset.lower().replace(' ', '_').replace('-', '_')}"
            self._kg.upsert_node(
                node_id=ds_id,
                node_type="dataset",
                label=dataset,
                properties={"name": dataset},
                text_corpus=dataset,
                change_reason="paper_ingestion",
            )
            self._kg.upsert_edge(doc_id, ds_id, "uses_dataset")

        # Factor nodes
        for feature in meta.get("features_mentioned", []):
            feat_id = f"factor:{feature.lower().replace(' ', '_').replace('-', '_')}"
            self._kg.upsert_node(
                node_id=feat_id,
                node_type="factor",
                label=feature,
                properties={"name": feature},
                text_corpus=feature,
                change_reason="paper_ingestion",
            )
            self._kg.upsert_edge(doc_id, feat_id, "uses_feature")

    def _stage_score(self, job: PipelineJob) -> None:
        score = score_paper(job.corpus_doc_id or job.id, job.paper_metadata)
        job.priority_score = score.total
        # Persist score summary in metadata
        job.paper_metadata["_score"] = score.model_dump()

    def _stage_plan_experiment(self, job: PipelineJob) -> None:
        if job.priority_score < self._cfg.min_priority_for_experiment:
            logger.info(
                "experiment_skipped_low_priority",
                job_id=job.id,
                score=job.priority_score,
                threshold=self._cfg.min_priority_for_experiment,
            )
            return
        spec = plan_experiment(
            paper_id=job.corpus_doc_id or job.id,
            meta=job.paper_metadata,
            priority_score=job.priority_score,
        )
        job.experiment_spec = spec.model_dump()
        # Write spec to experiments folder
        spec_path = self._cfg.experiments / f"{job.content_hash[:16]}_spec.json"
        spec_path.write_text(spec.model_dump_json(indent=2), encoding="utf-8")
        logger.info(
            "experiment_planned",
            job_id=job.id,
            ready=spec.ready_to_run,
            missing=spec.missing_prerequisites,
        )

    def _stage_archive(self, job: PipelineJob) -> None:
        src = Path(job.file_path)
        dst = self._cfg.processed / src.name
        if src.exists() and src.resolve() != dst.resolve():
            shutil.move(str(src), str(dst))
        job.file_path = str(dst)

    # ── helpers ───────────────────────────────────────────────────────────────

    def _run_stage(self, job: PipelineJob, name: str, fn, deadline: float) -> bool:
        while True:
            if time.monotonic() > deadline:
                raise IngestTimeoutError(
                    f"exceeded {self._cfg.per_file_timeout_seconds:.0f}s before stage '{name}'"
                )
            try:
                fn(job)
                result = StageResult(stage=name, status="success")
                job.stages.append(result)
                self._journal.record_stage(job.id, name, "success")
                return True
            except (PermanentIngestError, IngestTimeoutError) as exc:
                # Permanent failure — record diagnostics and reject immediately, no retry.
                job.stages.append(StageResult(stage=name, status="failed", message=str(exc)))
                self._journal.record_stage(job.id, name, "failed", str(exc))
                logger.error("stage_failed", job_id=job.id, stage=name, error=str(exc))
                raise
            except Exception as exc:
                result = StageResult(stage=name, status="failed", message=str(exc))
                job.stages.append(result)
                self._journal.record_stage(job.id, name, "failed", str(exc))
                logger.error("stage_failed", job_id=job.id, stage=name, error=str(exc))

                self._healer.attempt_repair(job, name, exc)
                if self._healer.should_retry(job, name, exc):
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise IngestTimeoutError(f"exceeded during retry of '{name}'") from exc
                    job.retry_count += 1
                    self._healer.wait_before_retry(job, max_wait=remaining)
                    continue
                return False

    def _reject(self, job: PipelineJob, reason: str) -> None:
        job.status = JobStatus.REJECTED
        job.error = reason
        src = Path(job.file_path)
        if src.exists():
            dst = self._cfg.rejected / src.name
            shutil.move(str(src), str(dst))
            job.file_path = str(dst)
        logger.error("job_rejected", job_id=job.id, reason=reason)

    def _save_metadata(self, job: PipelineJob) -> None:
        meta_path = self._cfg.metadata / f"{job.content_hash[:16] or job.id[:8]}.json"
        meta_path.write_text(job.model_dump_json(indent=2), encoding="utf-8")

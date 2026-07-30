"""Integration tests for the pipeline orchestrator using in-memory stores."""

import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from aurelius.corpus.models import CorpusDocument
from aurelius.operations.config import OperationsConfig
from aurelius.operations.extractor import _HAS_PYPDF
from aurelius.operations.models import JobStatus
from aurelius.operations.pipeline import PipelineOrchestrator


@pytest.fixture
def tmp_config(tmp_path):
    cfg = OperationsConfig(corpus_root=tmp_path / "corpus")
    cfg.ensure_dirs()
    return cfg


def _mock_corpus():
    """CorpusStore mock that returns a fake document on add_document."""
    store = MagicMock()
    doc = MagicMock(spec=CorpusDocument)
    doc.id = "doc-test-001"
    store.add_document.return_value = doc
    store.search.return_value = []  # no duplicates
    store.document_exists_by_hash.return_value = False  # exact-hash dedup: no dup
    return store


def _mock_kg():
    kg = MagicMock()
    kg.upsert_node.return_value = None
    kg.upsert_edge.return_value = None
    return kg


@pytest.fixture
def pipeline(tmp_config):
    return PipelineOrchestrator(tmp_config, _mock_corpus(), _mock_kg())


def _write_paper(path: Path, content: str = "") -> Path:
    path.write_text(content or "Title: Factor Momentum in Equity Markets\n\nAbstract: This paper examines momentum.\n\nMethodology: We use Fama-MacBeth regressions.\n\nResults: Sharpe ratio 1.4, t-stat 3.2.", encoding="utf-8")
    return path


def test_process_valid_txt_file(tmp_config, pipeline):
    paper = tmp_config.incoming / "test_paper.txt"
    _write_paper(paper)
    job = pipeline.process_file(paper)
    assert job.status == JobStatus.COMPLETED
    assert job.content_hash != ""
    assert job.corpus_doc_id == "doc-test-001"


def test_completed_job_has_all_stages(tmp_config, pipeline):
    paper = tmp_config.incoming / "test_paper2.txt"
    _write_paper(paper)
    job = pipeline.process_file(paper)
    stage_names = {s.stage for s in job.stages}
    assert "validate" in stage_names
    assert "extract_metadata" in stage_names
    assert "store_corpus" in stage_names
    assert "archive" in stage_names


def test_file_moved_to_processed(tmp_config, pipeline):
    paper = tmp_config.incoming / "test_paper3.txt"
    _write_paper(paper)
    job = pipeline.process_file(paper)
    assert job.status == JobStatus.COMPLETED
    # File should now be in processed/ not incoming/
    assert not (tmp_config.incoming / "test_paper3.txt").exists()
    assert (tmp_config.processed / "test_paper3.txt").exists()


def test_unsupported_extension_rejected(tmp_config, pipeline):
    bad_file = tmp_config.incoming / "paper.docx"
    bad_file.write_bytes(b"fake docx content")
    job = pipeline.process_file(bad_file)
    assert job.status == JobStatus.REJECTED


def test_empty_file_rejected(tmp_config, pipeline):
    empty = tmp_config.incoming / "empty.txt"
    empty.write_text("")
    job = pipeline.process_file(empty)
    assert job.status == JobStatus.REJECTED


def test_duplicate_detection(tmp_config, pipeline):
    # First paper processes fine
    paper1 = tmp_config.incoming / "paper_a.txt"
    _write_paper(paper1, "Unique content: " + "X" * 200)
    job1 = pipeline.process_file(paper1)
    assert job1.status == JobStatus.COMPLETED

    # Simulate corpus returning a hit (content already ingested)
    pipeline._corpus.document_exists_by_hash.return_value = True
    paper2 = tmp_config.incoming / "paper_b.txt"
    _write_paper(paper2, "Unique content: " + "X" * 200)
    job2 = pipeline.process_file(paper2)
    assert job2.status == JobStatus.REJECTED


def test_metadata_saved_to_disk(tmp_config, pipeline):
    paper = tmp_config.incoming / "meta_test.txt"
    _write_paper(paper)
    pipeline.process_file(paper)
    meta_files = list(tmp_config.metadata.glob("*.json"))
    assert len(meta_files) == 1


def test_high_priority_paper_gets_experiment_spec(tmp_config, pipeline):
    # Override min threshold to ensure spec is generated
    pipeline._cfg.min_priority_for_experiment = 0.0
    paper = tmp_config.incoming / "hipri.txt"
    _write_paper(paper, "Title: Momentum Strategy\n\nAbstract: " + "Momentum generates alpha. " * 20 + "\n\nMethodology: Fama-MacBeth with Ken French data.\n\nResults: Sharpe 1.8 t-stat 4.2.")
    job = pipeline.process_file(paper)
    assert job.status == JobStatus.COMPLETED
    assert job.experiment_spec is not None
    spec_files = list(tmp_config.experiments.glob("*_spec.json"))
    assert len(spec_files) == 1


def test_processing_time_recorded(tmp_config, pipeline):
    paper = tmp_config.incoming / "timing.txt"
    _write_paper(paper)
    job = pipeline.process_file(paper)
    assert job.processing_seconds >= 0.0


def test_resume_incomplete_finds_nothing_fresh(tmp_config, pipeline):
    # No interrupted jobs — should return empty list
    result = pipeline.resume_incomplete()
    assert result == []


# ── Phase 25 blocker remediation: corrupt/permanent/timeout handling ──────────


@pytest.mark.skipif(not _HAS_PYPDF, reason="pypdf required to exercise PDF parse failure")
def test_corrupt_pdf_rejected_without_retry_storm(tmp_config, pipeline):
    bad = tmp_config.incoming / "corrupt.pdf"
    bad.write_bytes(b"%PDF-1.4\ngarbage not a real pdf \x00\x01\x02 broken")
    t0 = time.monotonic()
    job = pipeline.process_file(bad)
    elapsed = time.monotonic() - t0

    assert job.status == JobStatus.REJECTED
    assert job.retry_count == 0  # permanent failure → never retried
    assert elapsed < 5.0  # no 7-minute backoff storm
    assert "Permanent failure" in job.error
    # processing/ cleaned up, file relocated to rejected/ with diagnostics
    assert not any(tmp_config.processing.iterdir())
    assert (tmp_config.rejected / "corrupt.pdf").exists()


def test_invalid_format_no_text_rejected_permanently(tmp_config, pipeline):
    # Extractor yields no usable text → permanent, immediate reject, no retry.
    with patch("aurelius.operations.pipeline.extract_text", return_value="   \n  "):
        paper = tmp_config.incoming / "blank.txt"
        _write_paper(paper)
        job = pipeline.process_file(paper)
    assert job.status == JobStatus.REJECTED
    assert job.retry_count == 0
    assert not any(tmp_config.processing.iterdir())


def test_per_file_timeout_rejects_and_cleans_up(tmp_config, pipeline):
    pipeline._cfg.per_file_timeout_seconds = 0.02

    def slow_validate(job):
        time.sleep(0.05)  # blow the deadline; next stage's check trips the timeout

    pipeline._stage_validate = slow_validate
    paper = tmp_config.incoming / "slow.txt"
    _write_paper(paper)
    job = pipeline.process_file(paper)

    assert job.status == JobStatus.REJECTED
    assert "Timeout" in job.error
    assert not any(tmp_config.processing.iterdir())


@pytest.mark.skipif(not _HAS_PYPDF, reason="pypdf required to exercise PDF parse failure")
def test_mixed_batch_continues_after_bad_file(tmp_config, pipeline):
    bad = tmp_config.incoming / "corrupt.pdf"
    bad.write_bytes(b"%PDF-1.4 hopelessly \x00 broken")
    good = tmp_config.incoming / "good.txt"
    _write_paper(good)

    # Sequential processing through the same orchestrator (batch semantics).
    bad_job = pipeline.process_file(bad)
    good_job = pipeline.process_file(good)

    assert bad_job.status == JobStatus.REJECTED
    assert good_job.status == JobStatus.COMPLETED  # poison file did not serialize the queue
    assert not any(tmp_config.processing.iterdir())
    assert (tmp_config.rejected / "corrupt.pdf").exists()
    assert (tmp_config.processed / "good.txt").exists()

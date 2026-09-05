"""Daily report generator — aggregates pipeline and corpus metrics into a report."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from mentisrex.core.logging import get_logger
from mentisrex.operations.config import OperationsConfig
from mentisrex.operations.journal import PipelineJournal
from mentisrex.operations.models import DailyReport

logger = get_logger(__name__)


class DailyReporter:
    def __init__(self, config: OperationsConfig) -> None:
        self._cfg = config
        self._journal = PipelineJournal(config.logs)

    def generate(self, date: datetime | None = None) -> DailyReport:
        """Generate a daily report for the given date (defaults to today UTC)."""
        target = date or datetime.now(UTC)
        start = target.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)

        entries = self._journal.load_range(start, end)
        job_updates = [e for e in entries if e.get("event") == "job_update"]

        # Deduplicate — take final state per job
        latest: dict[str, dict] = {}
        for e in job_updates:
            j = e["job"]
            latest[j["id"]] = j

        jobs = list(latest.values())
        completed = [j for j in jobs if j["status"] == "completed"]
        failed = [j for j in jobs if j["status"] == "failed"]
        rejected = [j for j in jobs if j["status"] == "rejected"]

        processing_times = [
            j.get("processing_seconds", 0) for j in completed if j.get("processing_seconds", 0) > 0
        ]
        avg_time = sum(processing_times) / len(processing_times) if processing_times else 0.0

        experiments_queued = sum(1 for j in completed if j.get("experiment_spec"))
        top_papers = sorted(
            [
                {
                    "title": j.get("paper_metadata", {}).get("title", j["original_filename"]),
                    "score": j.get("priority_score", 0),
                    "corpus_id": j.get("corpus_doc_id", ""),
                }
                for j in completed
                if j.get("priority_score", 0) > 0
            ],
            key=lambda x: x["score"],
            reverse=True,
        )[:10]

        failures = [
            {
                "filename": j["original_filename"],
                "status": j["status"],
                "error": j.get("error", ""),
            }
            for j in (failed + rejected)
        ]

        total = len(completed) + len(failed) + len(rejected)
        success_rate = len(completed) / total if total > 0 else 1.0

        # Corpus totals from metadata folder (persistent across days)
        corpus_total = (
            sum(1 for _ in self._cfg.metadata.glob("*.json")) if self._cfg.metadata.exists() else 0
        )

        report = DailyReport(
            date=target.strftime("%Y-%m-%d"),
            papers_ingested=len(completed),
            papers_failed=len(failed),
            papers_rejected=len(rejected),
            experiments_queued=experiments_queued,
            corpus_total=corpus_total,
            pipeline_success_rate=round(success_rate, 3),
            avg_processing_seconds=round(avg_time, 2),
            top_papers=top_papers,
            failures=failures,
        )

        self._save(report)
        logger.info("daily_report_generated", date=report.date, ingested=report.papers_ingested)
        return report

    def _save(self, report: DailyReport) -> None:
        self._cfg.reports.mkdir(parents=True, exist_ok=True)
        path = self._cfg.reports / f"report_{report.date}.json"
        path.write_text(report.model_dump_json(indent=2), encoding="utf-8")

    def load(self, date_str: str) -> DailyReport | None:
        path = self._cfg.reports / f"report_{date_str}.json"
        if not path.exists():
            return None
        try:
            return DailyReport.model_validate_json(path.read_text())
        except Exception as exc:
            logger.warning("report_load_failed", date=date_str, error=str(exc))
            return None

    def list_reports(self) -> list[str]:
        if not self._cfg.reports.exists():
            return []
        return sorted(
            p.stem.replace("report_", "") for p in self._cfg.reports.glob("report_*.json")
        )

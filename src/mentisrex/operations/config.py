"""Operations engine configuration."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class OperationsConfig:
    corpus_root: Path = field(default_factory=lambda: Path("research_corpus"))
    poll_interval_seconds: int = 30
    max_retries: int = 3
    retry_delay_seconds: int = 60
    per_file_timeout_seconds: float = 120.0  # wall-clock cap per document
    min_priority_for_experiment: float = 6.0
    max_concurrent_experiments: int = 3
    daily_report_hour: int = 8  # UTC hour to generate daily report

    @property
    def incoming(self) -> Path:
        return self.corpus_root / "incoming"

    @property
    def processing(self) -> Path:
        return self.corpus_root / "processing"

    @property
    def processed(self) -> Path:
        return self.corpus_root / "processed"

    @property
    def rejected(self) -> Path:
        return self.corpus_root / "rejected"

    @property
    def metadata(self) -> Path:
        return self.corpus_root / "metadata"

    @property
    def extracted(self) -> Path:
        return self.corpus_root / "extracted"

    @property
    def summaries(self) -> Path:
        return self.corpus_root / "summaries"

    @property
    def experiments(self) -> Path:
        return self.corpus_root / "experiments"

    @property
    def reports(self) -> Path:
        return self.corpus_root / "reports"

    @property
    def logs(self) -> Path:
        return self.corpus_root / "logs"

    def ensure_dirs(self) -> None:
        for d in (
            self.incoming,
            self.processing,
            self.processed,
            self.rejected,
            self.metadata,
            self.extracted,
            self.summaries,
            self.experiments,
            self.reports,
            self.logs,
        ):
            d.mkdir(parents=True, exist_ok=True)

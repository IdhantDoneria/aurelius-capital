"""Autonomous Research Operations Engine."""

from aurelius.operations.config import OperationsConfig
from aurelius.operations.models import (
    DailyReport,
    ExperimentSpec,
    HealthStatus,
    JobStatus,
    PaperScore,
    PipelineJob,
    StageResult,
)
from aurelius.operations.monitor import OperationsMonitor
from aurelius.operations.pipeline import PipelineOrchestrator
from aurelius.operations.reporter import DailyReporter
from aurelius.operations.watcher import FolderWatcher

__all__ = [
    "OperationsConfig",
    "PipelineJob",
    "JobStatus",
    "StageResult",
    "PaperScore",
    "ExperimentSpec",
    "DailyReport",
    "HealthStatus",
    "PipelineOrchestrator",
    "FolderWatcher",
    "OperationsMonitor",
    "DailyReporter",
]

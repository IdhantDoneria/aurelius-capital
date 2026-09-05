"""Polling-based folder watcher for the incoming research corpus directory.

Runs in a background thread. On each poll cycle, discovers new files in
incoming/, hands them to PipelineOrchestrator, and records results.
No watchdog dependency — polling is simpler and adequate for batch ingestion.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

from mentisrex.core.logging import get_logger
from mentisrex.operations.config import OperationsConfig

if TYPE_CHECKING:
    from mentisrex.operations.pipeline import PipelineOrchestrator

logger = get_logger(__name__)

_SUPPORTED_EXTENSIONS = {".pdf", ".txt", ".md", ".rst", ".tex", ".json"}


class FolderWatcher:
    """Monitors incoming/ folder and triggers pipeline for new files.

    Call start() to begin background polling. Call stop() to halt.
    Thread-safe: seen_files set is protected by a lock.
    """

    def __init__(self, config: OperationsConfig, pipeline: PipelineOrchestrator) -> None:
        self._cfg = config
        self._pipeline = pipeline
        self._seen: set[str] = set()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._running = False

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._cfg.ensure_dirs()
        # Pre-populate seen set with already-processed files (avoid reprocessing on restart)
        self._seed_seen_from_processed()
        self._thread = threading.Thread(target=self._poll_loop, daemon=True, name="FolderWatcher")
        self._thread.start()
        logger.info("folder_watcher_started", poll_interval=self._cfg.poll_interval_seconds)

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("folder_watcher_stopped")

    def process_now(self, file_path: Path) -> None:
        """Process a single file immediately (for API-triggered ingestion)."""
        self._process_file(file_path)

    # ── internals ─────────────────────────────────────────────────────────────

    def _poll_loop(self) -> None:
        while self._running:
            try:
                self._scan_incoming()
            except Exception as exc:
                logger.error("watcher_poll_error", error=str(exc))
            time.sleep(self._cfg.poll_interval_seconds)

    def _scan_incoming(self) -> None:
        incoming = self._cfg.incoming
        if not incoming.exists():
            return
        for path in incoming.iterdir():
            if path.is_file() and path.suffix.lower() in _SUPPORTED_EXTENSIONS:
                key = path.name
                with self._lock:
                    if key in self._seen:
                        continue
                    self._seen.add(key)
                self._process_file(path)

    def _process_file(self, path: Path) -> None:
        logger.info("watcher_new_file", filename=path.name)
        try:
            job = self._pipeline.process_file(path)
            logger.info(
                "watcher_file_done",
                filename=path.name,
                status=job.status,
                score=job.priority_score,
            )
        except Exception as exc:
            logger.error("watcher_process_error", filename=path.name, error=str(exc))

    def _seed_seen_from_processed(self) -> None:
        """Don't reprocess files already in processed/ or rejected/."""
        for folder in (self._cfg.processed, self._cfg.rejected):
            if folder.exists():
                for path in folder.iterdir():
                    if path.is_file():
                        self._seen.add(path.name)
        # Also seed from processing/ (in-flight on prior run → resume logic handles these)
        if self._cfg.processing.exists():
            for path in self._cfg.processing.iterdir():
                if path.is_file():
                    self._seen.add(path.name)

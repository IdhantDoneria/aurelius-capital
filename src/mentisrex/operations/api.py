"""FastAPI router for the autonomous research operations engine."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import HTMLResponse

from mentisrex.core.logging import get_logger
from mentisrex.operations.config import OperationsConfig
from mentisrex.operations.models import DailyReport, HealthStatus
from mentisrex.operations.monitor import OperationsMonitor
from mentisrex.operations.reporter import DailyReporter

logger = get_logger(__name__)

operations_router = APIRouter(prefix="/operations", tags=["operations"])

# Module-level singletons injected at app startup via configure()
_config: OperationsConfig | None = None
_monitor: OperationsMonitor | None = None
_reporter: DailyReporter | None = None
_pipeline = None  # PipelineOrchestrator
_watcher = None  # FolderWatcher


def configure(
    config: OperationsConfig,
    pipeline,
    monitor: OperationsMonitor,
    reporter: DailyReporter,
    watcher=None,
) -> None:
    global _config, _monitor, _reporter, _pipeline, _watcher
    _config = config
    _pipeline = pipeline
    _monitor = monitor
    _reporter = reporter
    _watcher = watcher


def _require_pipeline():
    if _pipeline is None:
        raise HTTPException(503, "Operations engine not initialized")
    return _pipeline


def _require_monitor():
    if _monitor is None:
        raise HTTPException(503, "Operations monitor not initialized")
    return _monitor


# ── health & metrics ─────────────────────────────────────────────────────────


@operations_router.get("/health", response_model=HealthStatus)
def get_health():
    return _require_monitor().health()


@operations_router.get("/metrics")
def get_metrics() -> dict:
    return _require_monitor().metrics()


# ── paper ingestion ───────────────────────────────────────────────────────────


@operations_router.post("/ingest/path", response_model=dict)
def ingest_from_path(payload: dict = Body(...)) -> dict:
    """Process a file already on disk by absolute path."""
    file_path = payload.get("path", "")
    if not file_path:
        raise HTTPException(400, "Missing 'path' in payload")
    path = Path(file_path)
    if not path.exists():
        raise HTTPException(404, f"File not found: {path}")
    job = _require_pipeline().process_file(path)
    return {
        "job_id": job.id,
        "status": job.status,
        "priority_score": job.priority_score,
        "corpus_doc_id": job.corpus_doc_id,
        "stages": [s.model_dump() for s in job.stages],
    }


# ── queue inspection ──────────────────────────────────────────────────────────


@operations_router.get("/queue")
def get_queue() -> dict:
    """Return current file counts in each pipeline folder."""
    config = _config or OperationsConfig()
    return {
        folder: sum(1 for p in path.iterdir() if p.is_file() and not p.name.startswith("."))
        if path.exists()
        else 0
        for folder, path in [
            ("incoming", config.incoming),
            ("processing", config.processing),
            ("processed", config.processed),
            ("rejected", config.rejected),
        ]
    }


@operations_router.get("/experiments")
def list_experiments() -> list[dict]:
    """Return all queued experiment specifications."""
    config = _config or OperationsConfig()
    if not config.experiments.exists():
        return []
    results = []
    for spec_file in sorted(config.experiments.glob("*_spec.json")):
        try:
            import json

            results.append(json.loads(spec_file.read_text()))
        except Exception:
            pass
    return results


# ── reports ───────────────────────────────────────────────────────────────────


@operations_router.get("/reports", response_model=list)
def list_reports() -> list:
    if _reporter is None:
        return []
    return _reporter.list_reports()


@operations_router.get("/reports/{date}", response_model=DailyReport)
def get_report(date: str) -> DailyReport:
    if _reporter is None:
        raise HTTPException(503, "Reporter not initialized")
    report = _reporter.load(date)
    if report is None:
        # Generate on-demand for today
        if date == datetime.now(UTC).strftime("%Y-%m-%d"):
            return _reporter.generate()
        raise HTTPException(404, f"Report not found for date: {date}")
    return report


@operations_router.post("/reports/generate", response_model=DailyReport)
def generate_report() -> DailyReport:
    if _reporter is None:
        raise HTTPException(503, "Reporter not initialized")
    return _reporter.generate()


# ── watcher control ───────────────────────────────────────────────────────────


@operations_router.post("/watcher/start")
def start_watcher() -> dict:
    if _watcher is None:
        raise HTTPException(503, "Watcher not configured")
    _watcher.start()
    return {"status": "started"}


@operations_router.post("/watcher/stop")
def stop_watcher() -> dict:
    if _watcher is None:
        raise HTTPException(503, "Watcher not configured")
    _watcher.stop()
    return {"status": "stopped"}


# ── dashboard ─────────────────────────────────────────────────────────────────


@operations_router.get("/dashboard", response_class=HTMLResponse)
def dashboard() -> HTMLResponse:
    monitor = _require_monitor()
    health = monitor.health()
    metrics = monitor.metrics()
    return HTMLResponse(_render_dashboard(health, metrics))


def _render_dashboard(health: HealthStatus, metrics: dict) -> str:
    status_color = {"healthy": "#22c55e", "degraded": "#f59e0b", "unhealthy": "#ef4444"}.get(
        health.status, "#94a3b8"
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta http-equiv="refresh" content="30">
  <title>Mentisrex Operations Dashboard</title>
  <style>
    body {{ font-family: monospace; background: #0f172a; color: #e2e8f0; margin: 0; padding: 24px; }}
    h1 {{ color: #f8fafc; margin-bottom: 4px; }}
    .subtitle {{ color: #94a3b8; font-size: 13px; margin-bottom: 24px; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 24px; }}
    .card {{ background: #1e293b; border-radius: 8px; padding: 16px; }}
    .card-label {{ color: #94a3b8; font-size: 11px; text-transform: uppercase; letter-spacing: 1px; }}
    .card-value {{ color: #f1f5f9; font-size: 28px; font-weight: bold; margin-top: 4px; }}
    .status-badge {{ display: inline-block; padding: 4px 12px; border-radius: 20px; font-size: 12px; font-weight: bold; background: {status_color}; color: #0f172a; }}
    table {{ width: 100%; border-collapse: collapse; background: #1e293b; border-radius: 8px; overflow: hidden; }}
    th {{ background: #334155; color: #94a3b8; padding: 10px 14px; text-align: left; font-size: 11px; text-transform: uppercase; }}
    td {{ padding: 10px 14px; border-top: 1px solid #334155; font-size: 13px; }}
    h2 {{ color: #94a3b8; font-size: 13px; text-transform: uppercase; letter-spacing: 1px; margin: 24px 0 8px; }}
  </style>
</head>
<body>
  <h1>Mentisrex Operations</h1>
  <div class="subtitle">Auto-refresh every 30s &nbsp;|&nbsp; {datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")} UTC</div>
  <div class="subtitle"><span class="status-badge">{health.status.upper()}</span></div>

  <div class="grid">
    <div class="card"><div class="card-label">Incoming Queue</div><div class="card-value">{health.incoming_queue_size}</div></div>
    <div class="card"><div class="card-label">Processing</div><div class="card-value">{health.processing_queue_size}</div></div>
    <div class="card"><div class="card-label">Processed Total</div><div class="card-value">{health.processed_total}</div></div>
    <div class="card"><div class="card-label">Rejected</div><div class="card-value">{health.rejected_total}</div></div>
    <div class="card"><div class="card-label">Today Processed</div><div class="card-value">{metrics.get("papers_processed_today", 0)}</div></div>
    <div class="card"><div class="card-label">Experiments Planned</div><div class="card-value">{metrics.get("experiments_planned_today", 0)}</div></div>
    <div class="card"><div class="card-label">Avg Score</div><div class="card-value">{metrics.get("avg_priority_score", 0):.1f}</div></div>
    <div class="card"><div class="card-label">Success Rate</div><div class="card-value">{metrics.get("pipeline_success_rate", 1.0):.0%}</div></div>
  </div>

  <h2>Component Health</h2>
  <table>
    <tr><th>Component</th><th>Status</th></tr>
    {"".join(f"<tr><td>{k}</td><td>{v}</td></tr>" for k, v in health.components.items())}
  </table>

  <h2>Stage Failure Counts (Today)</h2>
  <table>
    <tr><th>Stage</th><th>Failures</th></tr>
    {"".join(f"<tr><td>{k}</td><td>{v}</td></tr>" for k, v in metrics.get("stage_failure_counts", {}).items()) or "<tr><td colspan=2>None</td></tr>"}
  </table>
</body>
</html>"""

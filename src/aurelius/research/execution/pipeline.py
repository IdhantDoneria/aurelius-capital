"""Execution pipeline (AIDP Phase 8).

The fixed 10-step flow, driven as state-machine stages with hooks, per-stage timing,
cooperative cancellation, and failure recovery. No shortcuts: every run walks the
same stages in the same order. Composition only — each stage calls an existing
engine (matrix, backtester, metric engine, registry); none is reimplemented here.
"""

from __future__ import annotations

import time
import traceback
from pathlib import Path

from aurelius.research.execution import validator
from aurelius.research.execution.artifact_manager import ArtifactManager
from aurelius.research.execution.exceptions import CancelledError
from aurelius.research.execution.metrics import compute_metrics
from aurelius.research.execution.state_machine import State

# (state, stage fn, before-hook, after-hook)
def _stages():
    return [
        (State.VALIDATING, _validate, "before_validation", "after_validation"),
        (State.BUILDING_MATRIX, _build_matrix, "before_matrix", "after_matrix"),
        (State.RUNNING, _execute, "before_backtest", "after_backtest"),
        (State.GENERATING_METRICS, _metrics, "before_metrics", "after_metrics"),
        (State.WRITING_ARTIFACTS, _artifacts, None, None),
        (State.FINALIZING, _finalize, "before_registry_close", None),
    ]


def run_pipeline(session, *, start_state: State | None = None, stop_after: State | None = None):
    """Drive `session` through the pipeline. Returns the session in a terminal
    state (COMPLETED / FAILED / CANCELLED), or paused at `stop_after` for resume.
    Never raises for run failures."""
    stages = _stages()
    if start_state is not None:  # resume: skip already-completed stages
        order = [s[0] for s in stages]
        stages = stages[order.index(start_state):]

    for state, fn, before, after in stages:
        if session.cancel_requested:
            return _cancel(session)
        try:
            session.transition(state)
            if before:
                session.hooks.fire(before, session)
            if session.cancel_requested:            # a before-hook may cancel
                return _cancel(session)
            _timed(session, state, fn)
            if after:
                session.hooks.fire(after, session)
        except CancelledError:
            return _cancel(session)
        except Exception as exc:  # noqa: BLE001 — convert any stage error into recovery
            return _fail(session, exc)
        if stop_after is not None and state == stop_after:
            session.events.emit("run_paused", stage=session.state)
            return session

    session.transition(State.COMPLETED)
    session.events.emit("run_completed", stage=session.state, experiment_id=session.experiment_id)
    return session


def _timed(session, state, fn) -> None:
    t = time.perf_counter()
    fn(session)
    session.stage_timings[str(state)] = time.perf_counter() - t


# ── stages ────────────────────────────────────────────────────────────────────

def _validate(session) -> None:
    session.events.emit("validation_started", stage=session.state)
    validator.validate(session)
    session.events.emit("validation_passed", stage=session.state)


def _build_matrix(session) -> None:
    cfg = session.config
    if not cfg.build_matrix or session.matrix_engine is None:
        session.events.emit("matrix_skipped", stage=session.state)
        return
    session.events.emit("matrix_build_started", stage=session.state)
    session.matrix = session.matrix_engine.feature_matrix_as_of(
        cfg.as_of, universe=cfg.universe, features=cfg.features or None)
    for w in validator.consistency_check(session):
        session.events.emit("consistency_warning", stage=session.state, warning=w)
    session.events.emit("matrix_build_finished", stage=session.state,
                        rows=session.matrix.universe_size)


def _execute(session) -> None:
    session.events.emit("strategy_initialized", stage=session.state)
    session.events.emit("execution_started", stage=session.state)
    session.report = session.config.executor(session)
    session.events.emit("execution_completed", stage=session.state)


def _metrics(session) -> None:
    pm = getattr(session.report, "metrics", None)
    if pm is None:
        session.events.emit("metrics_skipped", stage=session.state, reason="no report")
        session.metrics = {}
        return
    session.metrics = compute_metrics(pm, benchmark_returns=session.config.benchmark_returns)
    session.events.emit("metrics_completed", stage=session.state, count=len(session.metrics))


def _artifacts(session) -> None:
    ArtifactManager(_artifact_dir(session)).write_all(session)
    session.events.emit("artifacts_written", stage=session.state, count=len(session.artifacts))


def _finalize(session) -> None:
    exp = session.experiment
    if exp is not None:
        # registry stores numeric metrics only; None (e.g. Alpha with no benchmark)
        # stays in the metrics.json artifact but is not written to the perf table.
        numeric = {k: v for k, v in session.metrics.items() if v is not None}
        session.registry.finish_experiment(
            exp, metrics=numeric, artifacts=_manifest_list(session.artifacts))
        session.events.emit("registry_updated", stage=session.state, experiment_id=exp.experiment_id)
    session.final_report = _final_report(session)


# ── recovery / cancellation ─────────────────────────────────────────────────────

def _fail(session, exc: BaseException):
    session.error = f"{type(exc).__name__}: {exc}"
    session.traceback = traceback.format_exc()
    session.transition(State.FAILED, error=session.error)
    session.events.emit("run_failed", stage=session.state, error=session.error)
    _persist_failure(session)
    return session


def _persist_failure(session) -> None:
    """Save whatever exists: partial metrics + artifacts to the registry, stack
    trace + event log to disk. Best-effort; recovery must never raise."""
    try:
        d = Path(_artifact_dir(session))
        d.mkdir(parents=True, exist_ok=True)
        (d / "traceback.txt").write_text(session.traceback or "")
        (d / "execution_log.json").write_text(_json(session.events.to_list()))
        if session.metrics:
            (d / "metrics.json").write_text(_json(session.metrics))
    except Exception:  # noqa: BLE001
        pass
    try:
        exp = session.experiment
        if exp is not None:
            exp.metrics = {k: v for k, v in session.metrics.items() if v is not None}
            exp.artifacts = _manifest_list(session.artifacts)
            session.registry.fail_experiment(exp, session.error or "unknown", notes="recovered")
    except Exception:  # noqa: BLE001
        pass


def _cancel(session):
    session.transition(State.CANCELLED)
    session.events.emit("run_cancelled", stage=session.state)
    try:
        exp = session.experiment
        if exp is not None:
            # registry has no dedicated cancelled status; record it explicitly
            exp.status = "cancelled"
            exp.error = "CANCELLED"
            from datetime import UTC, datetime
            exp.finished_at = datetime.now(UTC)
            exp.duration_seconds = 0.0
            session.registry.store.update_run(exp)
    except Exception:  # noqa: BLE001
        pass
    return session


# ── helpers ───────────────────────────────────────────────────────────────────

def _artifact_dir(session) -> str:
    if session.config.artifacts_dir:
        return session.config.artifacts_dir
    key = session.experiment_id or session.session_id
    return str(Path("./data/artifacts") / key)


def _manifest_list(manifest: dict) -> list[dict]:
    return [{"artifact_type": name, "artifact_location": m["location"], "artifact_hash": m["hash"]}
            for name, m in (manifest or {}).items()]


def _final_report(session) -> dict:
    return {
        "experiment_id": session.experiment_id,
        "session_id": session.session_id,
        "state": str(session.state),
        "metrics": session.metrics,
        "artifacts": session.artifacts,
        "stage_timings": session.stage_timings,
        "events": session.events.to_list(),
    }


def _json(obj) -> str:
    import json
    return json.dumps(obj, indent=2, sort_keys=True, default=str)

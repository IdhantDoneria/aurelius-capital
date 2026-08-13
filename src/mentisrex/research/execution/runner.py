"""ResearchRunner — the single orchestrator (AIDP M8).

Every research experiment on Mentisrex executes through this. No component calls the
backtester directly; `make_backtest_executor` is the one bridge, injected as a
run's executor. The runner owns the registry + matrix wiring and drives each run
through the certified pipeline.
"""

from __future__ import annotations

from mentisrex.research.execution.hooks import HookRegistry
from mentisrex.research.execution.pipeline import run_pipeline
from mentisrex.research.execution.scheduler import Scheduler
from mentisrex.research.execution.session import ResearchSession, RunConfiguration
from mentisrex.research.execution.state_machine import State
from mentisrex.research.execution.validator import ValidationError, validate
from mentisrex.research.experiment_registry import ExperimentRegistry


class ResearchRunner:
    def __init__(self, *, registry: ExperimentRegistry | None = None, matrix_engine=None,
                 hooks: HookRegistry | None = None) -> None:
        self.registry = registry or ExperimentRegistry()
        self.matrix_engine = matrix_engine
        self.hooks = hooks or HookRegistry()
        self.scheduler = Scheduler(self)

    # ── public API ──────────────────────────────────────────────────────────────

    def run(self, config: RunConfiguration, *, stop_after: State | None = None) -> ResearchSession:
        """Execute one run end-to-end (or pause after `stop_after` for resume).
        Always returns a session; run failures are recorded, not raised."""
        session = ResearchSession(config, registry=self.registry,
                                  matrix_engine=self.matrix_engine, hooks=self.hooks)
        # pipeline step 1 — registry start
        exp = self.registry.start_experiment(
            config.name, description=config.description, parameters=config.parameters,
            features=config.features, dataset_versions=config.dataset_versions,
            random_seed=config.random_seed)
        session.experiment = exp
        session.events.emit("registry_started", stage=session.state, experiment_id=exp.experiment_id)
        return run_pipeline(session, stop_after=stop_after)

    def resume(self, session: ResearchSession) -> ResearchSession:
        """Continue a paused (non-terminal) session from its next stage."""
        if session.sm.is_terminal:
            return session
        return run_pipeline(session, start_state=session.sm.next_state())

    def cancel(self, session: ResearchSession) -> ResearchSession:
        """Request cooperative cancellation. Takes effect at the next stage boundary
        (or immediately when the session is next resumed)."""
        session.request_cancel()
        return session

    def validate(self, config: RunConfiguration) -> list[str]:
        """Dry pre-flight validation. Returns issue list ([] = ok), never executes."""
        session = ResearchSession(config, registry=self.registry, matrix_engine=self.matrix_engine)
        try:
            validate(session)
            return []
        except ValidationError as e:
            return e.issues

    def compare(self, exp1: str, exp2: str) -> dict:
        return self.registry.compare(exp1, exp2)

    def replay(self, experiment_id: str, *, executor=None):
        """Reproduce a completed run from registry metadata alone.

        Returns the reconstructed definition. Strategy code can't be serialized into
        metadata, so the executor is injected: pass one to actually re-run (yielding
        the identical fingerprint), omit it to just get the plan. No git checkout —
        the commit is reported for the caller to check out (interface only)."""
        plan = self.registry.reproduce(experiment_id)
        if executor is None:
            return plan
        config = RunConfiguration(
            name=plan["name"], description=plan.get("description", ""),
            parameters=plan["parameters"], features=plan["features"],
            dataset_versions=plan["dataset_versions"], random_seed=plan["random_seed"],
            executor=executor)
        return self.run(config)

    def batch(self, configs: list[RunConfiguration], **kw):
        return self.scheduler.batch(configs, **kw)


def make_backtest_executor(strategy, data_feed, backtest_config=None):
    """The single bridge to the backtester. Returns an executor `(session) ->
    BacktestReport` that the platform runs inside the RUNNING stage."""
    def executor(session):
        from mentisrex.backtesting import BacktestEngine
        return BacktestEngine(strategy=strategy, data_feed=data_feed,
                              config=backtest_config).run()
    return executor

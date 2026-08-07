# AIDP M8 — Institutional Research Execution Platform

The single orchestrator for every research experiment on Aurelius. After M8,
**no component calls the backtester directly** — everything runs through
`ResearchRunner`, which drives a `ResearchSession` through a fixed, logged,
reproducible pipeline. Additive; M1–M7 APIs untouched.

Module: `src/aurelius/research/execution/`.

```python
runner = ResearchRunner(registry=registry, matrix_engine=matrix)   # DI
executor = make_backtest_executor(strategy, data_feed, backtest_config)  # the one bridge
config = RunConfiguration(name="momentum_v3", parameters={...}, features=[...],
                          dataset_versions=versions, random_seed=42, executor=executor)
session = runner.run(config)     # → COMPLETED, fully recorded + reproducible
```

## Architecture

Composition + dependency injection; every stage calls an existing certified engine,
none is reimplemented.

| File | Responsibility |
|---|---|
| `session.py` | immutable `RunConfiguration` + mutable `ResearchSession` (owns all execution state) |
| `state_machine.py` | `State` enum + legal-transition graph |
| `event_log.py` | structured, timestamped `Event` objects |
| `hooks.py` | `HookRegistry` — 9 named extension points |
| `validator.py` | pre-execution validation + matrix/registry consistency check |
| `metrics.py` | metric engine (extends the certified `PerformanceCalculator`) |
| `artifact_manager.py` | writes 9 artifacts, hashes + integrity-verifies them |
| `pipeline.py` | the 10-step flow: stages, hooks, timing, cancel, recovery |
| `scheduler.py` | single / batch / sweep / walk-forward / rolling |
| `runner.py` | `ResearchRunner` public API + `make_backtest_executor` |
| `quality.py` | completeness check of a finished session |
| `exceptions.py` | typed errors |

**Key decision — the executor is the injection seam.** Strategy + data feed +
backtest config are wrapped by `make_backtest_executor` into a
`(session) -> BacktestReport` callable, the *only* place `BacktestEngine` is
constructed. The platform stays strategy-agnostic and testable (inject any
executor), and the "nothing calls the backtester directly" rule holds by
construction.

## ResearchSession

One session owns one run's entire state — experiment, matrix, report, metrics,
artifacts, per-stage timings, state machine, event log. Nothing outside the
session mutates that state; the pipeline calls session methods and the session
records each transition. `RunConfiguration` is a frozen dataclass — the immutable,
fully-specified definition of a run (and the unit a future distributed backend
would ship to a worker).

## State machine

```
CREATED → VALIDATING → BUILDING_MATRIX → RUNNING → GENERATING_METRICS
        → WRITING_ARTIFACTS → FINALIZING → COMPLETED
   (any active state) → FAILED | CANCELLED
```

Transitions are validated against the graph; illegal ones raise
`StateTransitionError`. Every transition emits a `state_transition` event. `FAILED`
and `CANCELLED` are reachable from any active state; the three terminals are
absorbing.

## Execution flow (the 10 steps, no shortcuts)

1. **Registry start** (`runner.run`) — `start_experiment`, lineage auto-captured.
2. **Validation** (`VALIDATING`) — abort before any side effect if invalid.
3. **Matrix generation** (`BUILDING_MATRIX`) — M6 `feature_matrix_as_of`
   (skipped if `build_matrix=False`); consistency-checked against the registry.
4. **Strategy init** + 5. **Backtest execution** + 6. **Portfolio stats**
   (`RUNNING`) — the injected executor runs `BacktestEngine`, producing the report.
7. **Performance metrics** (`GENERATING_METRICS`) — the metric engine.
8. **Artifact generation** (`WRITING_ARTIFACTS`) — 9 files, hashed + verified.
9. **Registry update** + 10. **Final report** (`FINALIZING`) — `finish_experiment`
   with metrics + artifact hashes; the run's final report assembled.

Each stage is timed (`session.stage_timings`), wrapped in its before/after hooks,
and preceded by a cancellation check.

## Validation pipeline

Aborts before execution if any fail: strategy (executor callable), universe shape,
research-matrix availability, features registered (M6), dataset versions
present, feature registry present, registry available, parameters hashable, random
seed present. Advanced `consistency_check` compares built-matrix metadata to the
registry experiment (non-fatal warnings).

## Hooks

9 points fired around stages: `before_validation` / `after_validation`,
`before_matrix` / `after_matrix`, `before_backtest` / `after_backtest`,
`before_metrics` / `after_metrics`, `before_registry_close`. A hook receives the
session; under the default fail-fast policy a hook exception fails the run (a
broken plugin can't silently corrupt results). Cancellation is a one-line hook:
`before_backtest → session.request_cancel()`.

## Scheduler

Local, synchronous. `single`, `batch` (fail-fast or continue-on-error),
`parameter_sweep` (cartesian grid), `walk_forward` (per-`as_of` sequence),
`rolling_window` (per-`as_of` + lookback). All generate immutable
`RunConfiguration`s via `dataclasses.replace` and delegate to the runner — configs
are the parallelism unit a distributed backend would later consume. No distributed
execution yet (documented limitation).

## Metric engine

Does **not** duplicate the backtester's metrics. Reuses the certified
`PerformanceCalculator` output (Sharpe, Sortino, Calmar, CAGR, volatility, max
drawdown, turnover, win rate, profit factor, holding period) and *extends* it:
Alpha, Beta, Information Ratio (benchmark-relative), Hit Rate, Skew, Kurtosis, Tail
Ratio, Ulcer Index, Recovery Factor, Exposure, Expectancy, Average/Largest
Win/Loss, Average Trade — pure functions over the already-produced return/trade
series. Alpha/Beta/IR are `None` without a benchmark (kept in the artifact, omitted
from the registry's numeric table).

## Artifact formats

Nine artifacts per run, each hashed (blake2b) and integrity-verified by re-read:
`metrics.json`, `config.json`, `parameters.json`, `summary.json`,
`equity_curve.csv`, `positions.csv`, `transactions.csv`, `feature_manifest.json`,
`experiment_manifest.json` (the tie-together: experiment_id + fingerprint +
git_commit + dataset versions + artifact hashes). Hashes are stored back in the
registry. Deterministic JSON (sorted keys) → identical runs produce byte-identical
artifacts.

## Event model

Structured `Event(name, stage, timestamp, data)` objects (not string logs) — the
log is queryable (`by_name`) and serialized into the final report and failure dump.
Mirrored to the platform logger. Events cover registry start, every state
transition, validation, matrix build start/finish, execution start/complete,
metrics, artifacts, registry update, completion, failure, cancellation, pause.

## Failure recovery

Any stage exception is converted to recovery (never propagated as a crash): capture
the stack trace, transition to `FAILED`, persist to disk (`traceback.txt`,
`execution_log.json`, partial `metrics.json`) and to the registry
(`fail_experiment` with partial metrics + artifacts), then return the terminal
session. A batch continues (continue-on-error) or stops (fail-fast) per policy.

## Reproducibility

A completed run is re-executable from its Experiment ID + registry metadata:
`runner.replay(experiment_id, executor=...)` rebuilds the `RunConfiguration` from
`registry.reproduce` (dataset versions, features, parameters, seed, commit) and
re-runs it, yielding the identical fingerprint. **Git checkout is not implemented**
(by spec) — the commit is reported for the caller to check out; the strategy
executor is injected (code can't be serialized into metadata). This is the
designed interface boundary.

## Benchmarks (`scripts/benchmark_execution.py`, 500 runs, trivial executor)

| | Result |
|---|---|
| single-run overhead | ~46 ms (registry insert + git lineage capture) |
| batch throughput | ~39 runs/s |
| artifact generation | 0.98 ms (9 files + hashes + verify) |
| event logging | 12.6 µs/event |
| scheduler sweep | ~38 runs/s |

Orchestration overhead is negligible next to a real strategy backtest (seconds to
minutes). The single-run cost is dominated by the M7 registry write and the
per-run git subprocess in lineage capture.

## Test results (`tests/research/test_execution.py`, 14, all offline)

single · batch · parameter sweep · failure recovery · state transitions · event
logging · artifact generation · registry integration · research-matrix integration
· resume · cancel · validation failures · hook execution · a real `BacktestEngine`
run through the platform. Full suite: **141 passed, 2 skipped**, zero regressions.

## Known limitations / Skipped

- **No distributed execution.** Scheduler is local + synchronous; configs are the
  intended parallelism unit. Unblocked by a worker backend that consumes
  `RunConfiguration`s — deferred to M9.
- **Git checkout not implemented** (by spec). `replay` reports the commit and
  injects the executor; it does not restore the working tree.
- **Cancellation is cooperative** — it takes effect at stage boundaries (or when a
  paused session is resumed), not by interrupting a running backtest mid-stage.
- **Registry has no dedicated `cancelled` status** (M7); cancellation is
  recorded as `status="cancelled"` written via the store, with `error="CANCELLED"`.
- **Matrix consistency check is best-effort** — it warns, doesn't block, because
  the M6 matrix `data_versions` shape differs from the registry's 7-field set.

## Future distributed execution

The immutable `RunConfiguration` + the local `Scheduler` are the seam: a
distributed backend would serialize configs to a queue, execute
`run_pipeline(session)` on workers, and write results back to the shared registry
DB. Nothing in the session model assumes a single process; the only shared mutable
state is the registry (already DuckDB-backed and append-oriented). Progress
callbacks and pluggable fail-fast/continue policies are already in place to support
long-running distributed sweeps.

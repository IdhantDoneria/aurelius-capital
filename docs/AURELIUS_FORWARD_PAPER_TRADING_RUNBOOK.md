# Aurelius — Controlled Forward Paper-Trading Runbook

**Status**: OPERATIONAL (Post-M24 Checkpoint)
**Strategy**: `ew-momentum-exp` v1.0.0 — EXPERIMENTAL PAPER TRADING
**Run ID**: `FORWARD_RUN_ew-momentum-exp_v1.0.0_20260812T000000Z`
**Date activated**: 2026-08-12

---

> **MANDATORY DISCLAIMERS**
> - NO REAL CAPITAL WAS DEPLOYED.
> - NO STRATEGY PARAMETERS WERE OPTIMIZED USING FORWARD DATA.
> - FORWARD RESULTS ARE OBSERVATIONAL EVIDENCE AND ARE NOT YET A DEPLOYMENT OR PROFITABILITY DECISION.
> - This run uses EXPERIMENTAL_PAPER classification. No production approval has been granted.

---

## 1. Purpose

This runbook governs the controlled, fully-auditable forward paper-trading run that accumulates genuine forward observations for later M24 analysis. It documents the architecture, safety constraints, operating procedures, checkpoint/restart protocol, fault rehearsal results, and known limitations.

## 2. Architecture Overview

```
M20/M21 snapshot boundary
        │
        ▼
PaperTradingLoop (M23)
  ├── RebalanceScheduler  — monthly cadence
  ├── StrategyRuntime (M22)
  │     ├── EqualWeightMomentumLogic  — signal=1.0 per security with price>0
  │     ├── PortfolioEngine (M10)     — equal_weight, long_only
  │     └── PreTradeRiskGate (M13)   — max_position=0.20, max_gross_leverage=1.0
  ├── PaperTradingSession (M12)      — paper broker, no real money
  └── CycleRecord  →  ForwardPerformanceRecord
                              │
                              ▼
                   ForwardValidationEngine (M24)
                              │
                              ▼
                   ForwardValidationArtifact
```

All data flows through the M20/M21 boundary. Strategy logic never calls data providers directly.

## 3. Strategy Specification (Frozen)

| Field | Value |
|---|---|
| `strategy_id` | `ew-momentum-exp` |
| `version` | `1.0.0` |
| `strategy_type` | `EXPERIMENTAL_PAPER` |
| `validation_status` | `REQUIRES_REVIEW` |
| `research_artifact_id` | `SIM` |
| `validation_artifact_id` | `696a411bed6731a997c399584bfa9c4f` |
| `rebalance_frequency` | `monthly` |
| `universe` | AAPL, MSFT, GOOGL, AMZN, META, NVDA, TSLA, JPM, JNJ, V |
| `portfolio_construction` | `equal_weight`, `long_only`, `max_position_weight=0.20` |
| `risk_config` | `max_position=0.20`, `max_gross_leverage=1.0` |
| `starting_capital` | USD 1,000,000 (paper only) |
| `benchmark` | SPY |

The `configuration_fingerprint` is stamped once at module load in `scripts/forward_run/spec.py`. **Any change to the above fields requires a new strategy version and a separate review.**

Research lineage: SIM experiment from M9 validation, `overall_verdict=PASS`, `confidence_score=88.1`, `Sharpe=2.12`, `n=729 obs`.

## 4. Key Files

| Path | Role |
|---|---|
| `scripts/forward_run/spec.py` | Frozen `StrategySpecification` (single source of truth) |
| `scripts/forward_run/logic.py` | `EqualWeightMomentumLogic` — signal computation |
| `scripts/forward_run/run_forward.py` | Activation driver + CLI entry point |
| `data/forward_runs/FORWARD_RUN_*/` | Per-run output directory |
| `data/forward_runs/FORWARD_RUN_*/checkpoint.json` | Checkpoint (save/restore) |
| `data/forward_runs/FORWARD_RUN_*/cycle_records.json` | Persisted cycle records |
| `data/forward_runs/FORWARD_RUN_*/run_manifest.json` | Run manifest (strategy + capital + lineage) |
| `data/forward_runs/FORWARD_RUN_*/run_health.json` | Operational health counters |
| `src/aurelius/research/paper_trading/loop.py` | M23 `PaperTradingLoop` |
| `src/aurelius/research/paper_trading/checkpoint.py` | JSON checkpoint save/load |
| `src/aurelius/research/forward_validation/engine.py` | M24 `ForwardValidationEngine` |
| `tests/research/test_forward_activation.py` | 41 integration tests (10 verification points) |

## 5. Safety Constraints (Non-Negotiable)

- **No real capital**: `MockBroker` / `SimulatedBroker` only. No live broker adapter.
- **No exchange connectivity**: `execution_config.direct_provider_access = False`.
- **No live data calls from strategy logic**: all data from M20/M21 snapshot boundary.
- **No strategy parameter optimization using forward data**: signal rule is fixed at `signal=1.0` for `price>0`.
- **Fingerprint immutability**: `configuration_fingerprint` must not change after the first `process_snapshot` call. Verified in `TestStrategyFingerprintPreservation`.
- **No M25 work**: this run accumulates forward observations only; no deployment decision has been made.

## 6. Running the Forward Loop

### SIMULATION mode (offline, synthetic prices)

```bash
cd aurelius-capital
python scripts/forward_run/run_forward.py --mode SIMULATION --cycles 12
```

Options:
- `--cycles N` — number of monthly cycles (default 12)
- `--start YYYY-MM-DD` — start date for synthetic snapshots (default `2026-01-01`)
- `--checkpoint-every N` — checkpoint interval in evaluations (default 4)

Output is written to `data/forward_runs/FORWARD_RUN_ew-momentum-exp_v1.0.0_20260812T000000Z/`.

### Operational mode (M20/M21 snapshots)

Inject snapshots programmatically via `run_loop()`:

```python
from scripts.forward_run.run_forward import run_loop
loop = run_loop(snapshot_stream)  # snapshot_stream from M20/M21
fpr = loop.forward_record("ew-momentum-exp")
```

Snapshots must come from M20/M21 providers. Strategy logic must never fetch data directly.

## 7. Checkpoint / Restart Protocol

Checkpoints are JSON files written every `checkpoint_every` evaluations and at loop exit.

### Checkpoint schema

```json
{
  "version": 1,
  "cycle_seq": <int>,
  "seen_snapshots": [<fingerprint>, ...],
  "strategy_states": { "<strategy_id>": { ... } },
  "portfolio_states": { "<strategy_id>": { ... } },
  "broker_states": { "<strategy_id>": { ... } },
  "cycle_records": [ { ... }, ... ]
}
```

### Restart

```python
from aurelius.research.paper_trading.checkpoint import load_checkpoint
data = load_checkpoint("path/to/checkpoint.json")
loop = build_loop(registry)
loop.restore_from_checkpoint(data)
```

**Idempotency guarantee**: duplicate snapshots (same fingerprint) are silently skipped. A resumed loop processes no snapshot twice.

### Checkpoint test results

`TestCheckpointRestart` (5 tests) verifies:
- Checkpoint saves/loads with no state loss
- `cycle_seq` is preserved across restart
- `seen_snapshots` deduplication works post-restart
- Cycle records are identical before and after restart
- Orphaned checkpoint files do not corrupt loop state

## 8. M23 → M24 Smoke Test

`TestM23ToM24SmokeTest` (5 tests) verifies:
1. `ForwardValidationEngine.analyze(fpr, spec)` produces a valid `ForwardValidationArtifact`
2. `artifact.strategy_fingerprint == spec.configuration_fingerprint`
3. `artifact.forward_record_fingerprint == fpr.fingerprint()`
4. `artifact_fingerprint` is deterministic (same inputs → same hash)
5. M24 does not mutate `spec` (frozen dataclass invariant)

With 8 cycles, `sample_adequacy` is `INSUFFICIENT` or `PRELIMINARY` — this is expected. Extended forward observation is required before M24 analysis is meaningful.

## 9. Fault Rehearsal Results

`TestFaultRehearsal` (3 tests):
- **Duplicate snapshot skipped**: processing the same snapshot twice yields 1 cycle record (not 2). Idempotency confirmed.
- **Paused strategy skipped**: after `loop.pause_strategy()`, snapshots are skipped; `resume_strategy()` restores normal operation.
- **fail_closed behavior**: evaluation errors are caught and recorded as error results; loop continues without crashing.

## 10. Integration Verification Points

All 41 tests in `tests/research/test_forward_activation.py` pass (0 failures, 0 new skips).

| # | Class | What is verified |
|---|---|---|
| 1 | `TestM23ToM24SmokeTest` | M23 → M24 wire-up |
| 2 | `TestRunInitialization` | Loop, registry, readiness gate, manifest, broker type |
| 3 | `TestStrategyFingerprintPreservation` | Fingerprint constant throughout run |
| 4 | `TestCheckpointRestart` | Checkpoint integrity and restart fidelity |
| 5 | `TestForwardRecordPersistence` | Cycle accumulation, nav_series, serialization |
| 6 | `TestReconciliation` | Each cycle reconciles (M12 invariant) |
| 7 | `TestFaultRehearsal` | Duplicate snapshot, pause, fail_closed |
| 8 | `TestEvidenceImmutability` | CycleRecord frozen; forward record consistent |
| 9 | `TestNoStrategyMutation` | Fingerprint constant; adding cycles does not alter spec |
| 10 | `TestNoRealExecution` | MockBroker/SimulatedBroker only; no live adapter |

## 11. Bug Fixes Applied

### M23 Python 3.12 enum `str()` regression (`loop.py`)

Python 3.12 changed `str(StrEnum.MEMBER)` to return `"StrEnum.MEMBER"` instead of `"member_value"`. The lifecycle check in `add_strategy` used `str(spec.strategy_type) in (...)` which silently failed to match `EXPERIMENTAL_PAPER`, causing a `LoopError`.

**Fix**: removed the `str()` wrapper — direct comparison works because `StrategyType(str, Enum)` members are `str` instances that compare equal to their string values.

### M23 experimental paper skip in `_process_one` (`loop.py`)

`_process_one` re-checked the M22 registry state on every cycle but had no exemption for `EXPERIMENTAL_PAPER` strategies at `VALIDATED` state (unlike `add_strategy` which did). Every cycle was silently skipped.

**Fix**: added the same `permit_experimental` guard to `_process_one` matching the one in `add_strategy`.

### `ForwardPerformanceRecord` missing `fingerprint()` and `n_cycles` (`cycle.py`)

M24's `build_lineage` computes a `forward_record_fingerprint` but `ForwardPerformanceRecord` had no corresponding method. Tests and cross-module code could not independently verify the fingerprint.

**Fix**: added `fingerprint()` method (matches `build_lineage` computation: `_fp({strategy_id, strategy_version, n_cycles, cycle_ids})`) and `n_cycles` property (`len(self.cycles)`).

## 12. Known Limitations

1. **Synthetic price data**: SIMULATION mode uses deterministic prices drifting +0.5%/month. Not equivalent to Bloomberg/Refinitiv/institutional exchange data. All metrics from SIMULATION mode are for infrastructure testing only.
2. **Short sample**: 8–12 forward cycles is statistically insufficient for M24 analysis. `sample_adequacy` will report `INSUFFICIENT` or `PRELIMINARY`.
3. **No historical comparison**: `paper_backtest_comparison()` is only meaningful when a matching M9 backtest result is provided.
4. **PAPER_LIVE_FEED mode not wired in CLI**: only SIMULATION is available from `run_forward.py --mode SIMULATION`. Live feed requires external snapshot injection via `run_loop()`.
5. **No M25**: This activation does not constitute a deployment decision. Do not begin M25 work until M24 produces an `APPROVED` recommendation with sufficient sample size.

## 13. Stopping Conditions

The loop stops automatically if:
- `sync_event.reconciled == False` (M12 reconciliation failure — critical)
- The snapshot stream is exhausted

Manual stop: interrupt the process. The final checkpoint is saved before exit.

## 14. Escalation

If any of the following occur, stop the loop and investigate before resuming:
- `reconciliation_failures > 0` in `run_health.json`
- `error_count / evaluation_count > 0.05` (>5% error rate)
- Strategy fingerprint changes between runs
- Any live broker adapter or real network call is detected

---

*Generated 2026-08-12. Controlled by CLAUDE.md commit discipline.*

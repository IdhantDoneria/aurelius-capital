# MENTISREX M23 — Continuous Paper Trading & Forward Simulation Runtime

**Status:** Implemented and certified  
**Milestone:** M23  
**Commit base:** M22 (a1cb836)  
**Author:** Claude Sonnet 4.6

---

## 1. Purpose

M23 adds a **continuous, persistent, auditable paper-trading runtime** to the Mentisrex platform. It orchestrates M22 strategy evaluation against M12 paper execution, maintaining live portfolio state across multiple snapshots and multiple strategies, with full checkpoint/restart support and forward performance recording.

M23 does **not** implement any of the following — they remain in their respective milestones:
- Strategy evaluation logic (M22 `StrategyRuntime`)
- Portfolio construction (M10 `PortfolioEngine`)
- Risk analytics (M13 `RiskEngine`)
- Paper execution (M12 `PaperTradingSession`)
- Market-data infrastructure (M20/M21)

---

## 2. Architecture

```
                        ┌─────────────────────────────────┐
  Snapshot stream  ───▶ │     PaperTradingLoop (M23)      │
                        │                                 │
                        │  for each active strategy:      │
                        │    1. M22 StrategyRuntime       │
                        │       .evaluate(spec, logic,    │
                        │        snapshot, portfolio)     │
                        │         ↓                       │
                        │    2. Extract target_weights    │
                        │       (empty if risk rejected)  │
                        │         ↓                       │
                        │    3. M12 PaperTradingSession   │
                        │       .step(as_of, weights,     │
                        │        prices)                  │
                        │         ↓                       │
                        │    4. Record CycleRecord        │
                        └─────────────────────────────────┘
                                    │
                         ┌──────────┴──────────┐
                         │                     │
                  Checkpoint file     ForwardPerformanceRecord
                  (JSON, no DB)       (NAV series, Sharpe, MDD)
```

### Key design principles

- **Fail-closed**: risk rejected → empty `target_weights` → no orders. Evaluation error → `StrategyCycleResult.error` (no crash when `fail_closed=True`).
- **Idempotent**: duplicate snapshot fingerprints are silently skipped. `_seen: set[str]` is persisted in checkpoints so restarts are also idempotent.
- **No duplication of M12**: M23 calls `PaperTradingSession.step()` — it does not re-implement order generation, filling, reconciliation, or drift.
- **No duplication of M22**: M23 calls `StrategyRuntime.evaluate()` — it does not re-implement feature computation, signal generation, portfolio construction, or risk checks.

---

## 3. Module map

| Module | Role |
|--------|------|
| `paper_trading/loop.py` | `PaperTradingLoop` — main orchestrator |
| `paper_trading/scheduler.py` | `RebalanceScheduler`, `Clock`, `FixedClock` |
| `paper_trading/runtime_state.py` | `StrategyRuntimeState` — mutable operational state |
| `paper_trading/cycle.py` | `CycleRecord`, `ForwardPerformanceRecord`, `PerformanceMetrics` |
| `paper_trading/checkpoint.py` | JSON-based checkpoint save/load |

All are exported from `mentisrex.research.paper_trading` and importable from their submodules directly.

---

## 4. Rebalance scheduling

`RebalanceScheduler.is_due(spec, runtime_state, snapshot_date)` determines whether evaluation is due.

| Frequency | Rule |
|-----------|------|
| `daily` | `snapshot_date > last_eval_date` |
| `weekly` | ≥ 7 calendar days since last evaluation |
| `monthly` | Calendar month has advanced |
| `quarterly` | Calendar quarter has advanced |
| `event_driven` | Never automatically (must use `loop.trigger_evaluation()`) |
| unknown | Treated as `daily` |

First evaluation (no `last_eval_date`) is always due.

---

## 5. Clock injection

```python
from mentisrex.research.paper_trading import Clock, FixedClock

# Tests and replay
clock = FixedClock(datetime(2024, 1, 2, 9, 30, 0))

# Production
clock = Clock()  # uses datetime.utcnow()

loop = PaperTradingLoop(runtime=..., registry=..., clock=clock)
```

---

## 6. Loop lifecycle

### Setup

```python
from mentisrex.research.paper_trading.loop import PaperTradingLoop, LoopConfig

config = LoopConfig(
    initial_capital=1_000_000.0,
    fail_closed=True,
    validate_readiness=True,
    mode="SIMULATION",
)
loop = PaperTradingLoop(runtime=m22_runtime, registry=m22_registry, config=config)
loop.add_strategy("strategy-abc", my_logic)
```

### Strategy requirements for `add_strategy()`

1. Strategy must be in `DEPLOYABLE` or `PAPER` state in the M22 registry.
2. If `validate_readiness=True`, `ReadinessValidator.validate()` must pass.
3. Experimental strategies (`EXPERIMENTAL_PAPER` type in `VALIDATED` state) require `permit_experimental=True`.

### Processing

```python
for snapshot in snapshot_stream:
    result = loop.process_snapshot(snapshot)
    for sr in result.strategy_results:
        print(sr.strategy_id, sr.portfolio_value, sr.risk_approved)
```

### Querying results

```python
fpr = loop.forward_record("strategy-abc")
metrics = fpr.metrics()
print(f"Total return: {metrics.total_return:.2%}")
print(f"Max drawdown: {metrics.max_drawdown:.2%}")
print(f"Fill rate: {metrics.fill_rate:.2%}")
```

---

## 7. StrategyRuntimeState

Mutable operational state, separate from M22's immutable `StrategySpecification`:

```python
@dataclass
class StrategyRuntimeState:
    strategy_id: str
    strategy_version: str
    strategy_fingerprint: str
    last_eval_date: date | None
    evaluation_count: int
    error_count: int
    status: str  # "active" | "paused"
    # ... fingerprint fields
```

- `status = "paused"` is an operational pause only; it does **not** touch the M22 registry lifecycle.
- `to_dict() / from_dict()` for checkpoint serialization.

---

## 8. Pause / resume

```python
loop.pause_strategy("strategy-abc", reason="manual hold during earnings")
# ... later
loop.resume_strategy("strategy-abc")  # revalidates M22 lifecycle state
```

Paused strategies produce `StrategyCycleResult(skipped=True, skip_reason="paused")`.

---

## 9. Event-driven / manual trigger

```python
# event_driven strategies skip automatic scheduling
loop.trigger_evaluation("strategy-abc", event_snapshot)
```

`trigger_evaluation()` bypasses the schedule check, allowing external events (e.g., earnings, corporate actions) to force evaluation.

---

## 10. Cost-model bridge

M22 `transaction_cost_assumption` is mapped to M12 execution parameters:

| M22 key | M12/M14 mapping |
|---------|-----------------|
| `slippage_bps` | `SimulatedBroker(slippage_bps=...)` |
| `commission_per_share` | passed through |
| `spread_bps` | passed through |
| other keys | logged as `unmapped_keys` |

```python
from mentisrex.research.paper_trading.loop import check_cost_compatibility

result = check_cost_compatibility(spec)
if not result.compatible:
    print(f"Unmapped cost keys: {result.unmapped_keys}")
    print(f"Issues: {result.issues}")
```

If `slippage_bps > 0`, `add_strategy()` automatically creates a `SimulatedBroker`. Otherwise uses `MockBroker`. A custom broker can be injected:

```python
loop.add_strategy("s", logic, broker=my_broker)
```

---

## 11. Checkpoint / restart

```python
from mentisrex.research.paper_trading.checkpoint import save_checkpoint, load_checkpoint
from mentisrex.research.paper_trading.checkpoint import _restore_checkpoint

# Save
save_checkpoint("/tmp/loop_state.json", loop)

# Restart
loop_new = PaperTradingLoop(runtime=..., registry=...)
loop_new.add_strategy("s", logic)
data = load_checkpoint("/tmp/loop_state.json")
_restore_checkpoint(loop_new, data)

# Continue processing
loop_new.process_snapshot(next_snapshot)
```

### What is saved

| Field | Description |
|-------|-------------|
| `cycle_seq` | Global cycle counter |
| `seen_snapshots` | Set of processed snapshot fingerprints (idempotency) |
| `strategy_states` | `StrategyRuntimeState.to_dict()` per strategy |
| `portfolio_states` | Cash, holdings, realized P&L per strategy |
| `broker_states` | Broker internal book + order sequence |
| `session_seqs` | Session sequence counter |
| `session_last_dates` | Last processed date |
| `session_total_costs` | Cumulative costs |
| `session_sync_events` | Full sync event history |
| `book_applied_fill_ids` | Fill deduplication set |
| `session_applied_fill_ids` | Session fill tracking |
| `cycle_records` | All `CycleRecord` instances |

**No secrets or credentials are saved.** Checkpoint files contain only numerical and structural state.

### Portfolio restore

Cash is restored via a synthetic `CashLedger` entry (`kind="checkpoint_restore"`) so `ledger.reconciles()` passes after restoration without losing the `initial_capital` reference.

---

## 12. Multi-strategy support

Each strategy has fully isolated state:

```python
loop.add_strategy("momentum", momentum_logic, initial_capital=500_000.0)
loop.add_strategy("mean-rev", mean_rev_logic, initial_capital=250_000.0)

result = loop.process_snapshot(snapshot)
for sr in result.strategy_results:
    print(f"{sr.strategy_id}: NAV={sr.portfolio_value:.0f}")
```

- Separate `PaperTradingSession` (separate broker, separate book)
- Separate `StrategyRuntimeState`
- Separate `CycleRecord` history
- One strategy's failure does not affect others (fail-closed per strategy)

---

## 13. Forward performance record

```python
fpr = loop.forward_record("strategy-abc")

# NAV series
for as_of, nav in fpr.nav_series():
    print(as_of, nav)

# Metrics
m = fpr.metrics(periods_per_year=252)
# m.total_return, m.max_drawdown, m.sharpe, m.volatility
# m.fill_rate, m.risk_approval_rate, m.total_fills, m.total_orders

# Research vs paper comparison
cmp = fpr.paper_backtest_comparison(research_capital=100_000.0)
print(cmp.paper_total_return, cmp.fill_rate)
```

`PaperBacktestComparison` notes that paper trading uses M21 open/free data, which is not equivalent to institutional feeds.

---

## 14. LoopCycleResult / StrategyCycleResult

```python
result = loop.process_snapshot(snapshot)

# Whole-loop result
result.cycle_id          # "cycle-000001"
result.as_of             # date
result.snapshot_fingerprint
result.skipped           # True if duplicate snapshot
result.skip_reason       # "duplicate_snapshot"

# Per-strategy result
sr = result.result_for("strategy-abc")
sr.strategy_id
sr.skipped               # True if not due / paused / lifecycle skip
sr.skip_reason           # "not_due" | "paused" | "lifecycle_suspended" | ...
sr.error                 # non-empty if evaluation failed (fail_closed=True)
sr.evaluation            # M22 StrategyEvaluation (None if skipped/error)
sr.sync_event            # M12 SyncEvent (n_orders, n_fills, reconciled, ...)
sr.cycle_record          # CycleRecord (None if skipped)
sr.portfolio_value
sr.cash
sr.realized_pnl
sr.risk_approved
```

---

## 15. Fail-closed behavior

| Situation | Behavior |
|-----------|----------|
| Risk rejected | `target_weights = {}` → no orders. `risk_approved=False` in result. |
| M22 evaluation error | `StrategyCycleResult.error` set. No crash. `error_count` incremented. |
| M12 step error | `StrategyCycleResult.error` set. No crash. |
| `fail_closed=False` | Exception propagates to caller. |
| `snapshot is None` | `LoopError` raised immediately. |
| `snapshot.as_of is None` | `LoopError` raised immediately. |

---

## 16. Operating modes

| Mode | Description |
|------|-------------|
| `SIMULATION` | Deterministic fixture data, no external calls (default) |
| `REPLAY` | Historical M20 replay, no external calls |
| `PAPER_LIVE_FEED` | Live/delayed M21 open data through M20 |

Mode is informational — it does not change the runtime behavior. Inject the appropriate data source via the snapshot stream.

---

## 17. Fingerprinting and determinism

- Snapshot fingerprint: `blake2b({"as_of": ..., "spots": ...})` — same as M7/M22 pattern.
- Cycle record fingerprint: derived from `evaluation_fingerprint` + `snapshot_fingerprint`.
- `evaluation_fingerprint`: deterministic per M22 (same strategy + same snapshot + same config → same fingerprint).
- Replay guarantee: same snapshot sequence → same final NAV and portfolio state.

---

## 18. Integration seams

| M23 calls | Milestone |
|-----------|-----------|
| `StrategyRuntime.evaluate(spec, logic, snapshot, portfolio_state)` | M22 |
| `PaperTradingSession.step(as_of, target_weights, prices)` | M12 |
| `PaperPortfolio` (via session) | M12 |
| `PortfolioState` (via session.book.state) | M11 |
| `SimulatedBroker / MockBroker` | M12 |
| `ReadinessValidator.validate(spec)` | M22 |
| `StrategyRegistry.state() / .spec()` | M22 |

---

## 19. Test coverage

**File:** `tests/research/test_paper_trading_runtime.py`  
**Tests:** 136 passing

| Section | Coverage |
|---------|----------|
| A. RebalanceScheduler + Clock | 15 tests |
| B. StrategyRuntimeState | 5 tests |
| C. CycleRecord / ForwardPerformanceRecord | 13 tests |
| D. Checkpoint save/load | 9 tests |
| E. Loop basic lifecycle | 18 tests |
| F. Idempotency | 6 tests |
| G. Scheduling via loop | 7 tests |
| H. Strategy lifecycle | 8 tests |
| I. Multi-strategy | 4 tests |
| J. Cost-model compatibility | 6 tests |
| K. Failure handling | 7 tests |
| L. M22→M12 integration | 10 tests |
| M. Multi-day continuity | 5 tests |
| N. Restart certification | 5 tests |
| O. Determinism / replay | 6 tests |
| P. Forward record / comparison | 5 tests |
| Q. End-to-end certification | 1 test |
| R. Partial-fill / duplicates | 5 tests |

All tests run offline with no network access. All inputs are deterministic (`FakeSnapshot`, `ConstantLogic`).

---

## 20. Known limitations

### Skipped items (by spec constraint)

1. **Persistent broker adapter**: M23 has no real brokerage connectivity. The M12 `BrokerAdapter` interface exists for wiring, but M23 remains paper-trading only.

2. **Corporate action replay through checkpoint**: `CorporateAction` objects (M15) are not serialized in checkpoints. If a corporate action occurs between a checkpoint and a restart, holdings must be re-adjusted manually. **Unblocked by**: M15 corporate action event stream support in checkpoint schema.

3. **Partial-fill simulation with real ADV**: `SimulatedBroker` accepts `fill_ratio` and `slippage_bps` but does not consume real ADV data. Real ADV injection requires M20 data flow wiring. **Unblocked by**: injecting ADV provider into `PaperTradingSession.step()`.

4. **Intraday snapshots**: Scheduling is day-granular. Sub-daily scheduling (hourly, tick-level) is not implemented. **Unblocked by**: extending `RebalanceScheduler` with datetime-aware scheduling and a sub-daily `FixedClock`.

---

## 21. Security constraints

- **No real-money trading**: M23 is paper-trading only. No real broker credentials, no real order routing, no capital deployment.
- **No network calls**: All M23 code is offline. Data arrives via the injected snapshot stream.
- **No secrets in checkpoints**: Checkpoint JSON contains only numerical/structural state. No API keys, credentials, or tokens.
- **No duplication**: M23 does not re-implement M10–M22 logic. All computation is delegated.

---

*Document generated for AIDP M23. Last updated: 2026-08-12.*

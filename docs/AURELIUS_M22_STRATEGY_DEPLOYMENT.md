# Mentisrex M22 — Strategy Deployment Layer

## 1. Objective

M22 establishes the formal, versioned contract between validated research and the existing Mentisrex execution and paper-trading infrastructure (M9–M21). It is a **seam**, not a replacement for any downstream system.

```
Research Artifact (M7/M8/M9)
↓
Validation Gate (M9 ValidationReport)
↓
StrategySpecification (M22 — immutable, versioned)
↓
DeploymentManifest (M22 — deterministic fingerprint)
↓
MarketDataSnapshot (M19/M20/M21)
↓
StrategyRuntime.evaluate() (M22)
│
├─ compute_features()     → FeatureSet
├─ generate_signal()      → SignalSet
├─ M10 PortfolioEngine    → Portfolio (targets)
├─ M13 RiskEngine         → RiskReport (pre-trade gate)
└─ M14 intents_from_target → OrderIntentRecord + OrderRequest
                                    ↓
                              M14 EMS / M12 PaperTradingSession
                                    ↓
                              M15 Post Trade / M11 Accounting
```

M22 does **not** implement:
- A new backtesting engine
- A new execution engine
- A new portfolio construction engine
- A new risk engine
- A new market-data pipeline
- A new order management system

## 2. Architecture

**Module:** `src/mentisrex/research/strategy_deployment/`

| File | Purpose |
|---|---|
| `models.py` | All immutable domain models |
| `lifecycle.py` | *(in models.py)* — StrategyState enum + ALLOWED_TRANSITIONS |
| `registry.py` | In-memory strategy registry (spec + state) |
| `runtime.py` | StrategyRuntime + StrategyLogic ABC |
| `readiness.py` | ReadinessValidator — deployment gate |
| `consistency.py` | ConsistencyChecker — research/deployment drift |
| `__init__.py` | Public API surface |

**Tests:** `tests/research/test_strategy_deployment.py` (88 tests)

## 3. Strategy Specification

`StrategySpecification` is a frozen dataclass — immutable once created. Use `make_spec(**kwargs)` to construct; it stamps the `configuration_fingerprint` automatically.

Material fields that affect the fingerprint:
- `strategy_id`, `version`, `strategy_type`
- `universe_definition`, `required_data`
- `feature_definition`, `signal_definition`
- `rebalance_frequency`
- `portfolio_construction_config`, `risk_config`, `execution_config`
- `transaction_cost_assumption`, `slippage_assumption`
- `benchmark`, `base_currency`, `allowed_instruments`
- `capital_assumption`, `model_version`, `validation_status`

`creation_timestamp` is **not** part of the fingerprint (operational metadata only).

## 4. Lifecycle

```
DRAFT → VALIDATING → VALIDATED → DEPLOYABLE → PAPER
                  ↘             ↘             ↘
                   REJECTED      REJECTED      SUSPENDED → RETIRED
```

All transitions are explicit via `StrategyRegistry.transition()`. Invalid transitions raise `StrategyTransitionError`. Terminal states (`RETIRED`, `REJECTED`) have no outbound transitions.

## 5. Research Binding

Every `StrategySpecification` carries:
- `research_artifact_id` — M7 experiment_id
- `validation_artifact_id` — M9 manifest_hash
- `validation_status` — M9 verdict (`PASS`, `PASS_WITH_WARNINGS`, `REJECT`, `REQUIRES_REVIEW`)

The `ReadinessValidator` checks both are present before permitting `DEPLOYABLE` status.

## 6. Feature / Signal Contract

Users implement `StrategyLogic` (ABC):

```python
class MyLogic(StrategyLogic):
    def compute_features(self, snapshot: MarketDataSnapshot, spec: StrategySpecification) -> FeatureSet:
        ...
    def generate_signal(self, features: FeatureSet, spec: StrategySpecification) -> SignalSet:
        ...
```

Invariants enforced by the runtime:
- `FeatureSet.as_of` must equal `snapshot.as_of` (PIT enforcement)
- `SignalSet.as_of` must equal `snapshot.as_of` (PIT enforcement)
- All signal values must be finite floats (NaN/Inf raises `EvaluationError`)
- Logic receives only the snapshot — no external provider access permitted

## 7. Runtime

```python
rt = StrategyRuntime(portfolio_engine=..., risk_engine=...)
evaluation = rt.evaluate(spec, logic, snapshot, portfolio_state)
```

Returns `StrategyEvaluation` containing:
- `feature_set`, `signal_set`
- `portfolio` (M10)
- `risk_report`, `risk_approved`, `risk_decision` (M13)
- `order_intents` (M22 `OrderIntentRecord` list — full lineage)
- `ems_requests` (M14 `OrderRequest` list — execution-ready)
- `evaluation_fingerprint` — deterministic hash

**Determinism guarantee:** Same `(spec, snapshot, portfolio_state)` → same `evaluation_fingerprint`.

## 8. Portfolio Construction Integration

Delegates to `M10 PortfolioEngine.construct()`. `portfolio_construction_config` is passed through:

```python
portfolio_construction_config = {
    "objective": "equal_weight",   # M10 Objective enum value
    "long_only": True,             # maps to ConstraintSet.long_only
    "max_position_weight": 0.10,   # maps to ConstraintSet.max_position_weight
}
```

No portfolio optimization logic exists in M22.

## 9. Risk Integration

Delegates to `M13 RiskEngine.pre_trade_check(target_weights)`.

- `REJECT` decision → `risk_approved=False`, `ems_requests=[]`, warning logged
- `APPROVE` / `APPROVE_WITH_WARNING` → intents proceed to EMS

The full `RiskReport` is attached to `StrategyEvaluation` for audit.

## 10. Order Intent

`OrderIntentRecord` is M22's enriched order intent. Each record carries:
- Full strategy lineage (`strategy_id`, `version`, `configuration_fingerprint`)
- Signal provenance (`signal_reference`)
- Portfolio provenance (`target_reference`)
- Risk provenance (`risk_reference`)

`record.to_ems_intent()` returns the M14 `OrderIntent` for direct use by the EMS.

## 11. Execution Integration

M22 terminates at the M14 boundary. `ems_requests` is a list of M14 `OrderRequest` objects ready for `EMS.execute(requests, market, ...)`. M22 does not run the EMS itself.

## 12. Paper-Trading Integration

`ems_requests` may also be passed to `M12 PaperTradingSession.step()` after converting quantities to target share books via `M11 intents_from_target`. The M12 session owns reconciliation and drift monitoring.

## 13. Versioning

Any change to a material field requires a new `version`. The old spec is never mutated — frozen dataclass enforces this. A paper strategy is pinned to the spec version it was registered under.

## 14. Deployment Manifests

`make_manifest(manifest_id, spec)` produces a `DeploymentManifest` — a deterministic snapshot of all configuration needed to reconstruct the runtime. The `manifest_fingerprint` excludes `created_at` (operational) and is stable for the same manifest_id + spec content.

## 15. Replayability

Same `(spec, snapshot, portfolio_state)` always produces the same `evaluation_fingerprint`. Historical replay uses M20 `MarketDataReplayEngine` to feed historical `MarketDataSnapshot` objects into `StrategyRuntime.evaluate()` — the output is bit-for-bit identical.

## 16. Readiness Gates

`ReadinessValidator.validate(spec)` checks 17 preconditions. A strategy is NOT ready if:

| Check | Failure |
|---|---|
| `research_artifact_exists` | No `research_artifact_id` |
| `validation_artifact_exists` | No `validation_artifact_id` |
| `validation_status_permits_deployment` | Status not in `{PASS, PASS_WITH_WARNINGS}` |
| `strategy_version_present` | Empty version string |
| `universe_definition_present` | Empty universe definition |
| `portfolio_construction_config_present` | Empty config |
| `risk_config_present` | Empty risk config |
| `cost_assumptions_explicit` | Empty `transaction_cost_assumption` |
| `base_currency_defined` | Empty base currency |
| `capital_assumption_positive` | Capital ≤ 0 |
| `rebalance_frequency_valid` | Not in `{daily, weekly, monthly, quarterly}` |
| `signal_definition_present` | Empty signal config |
| `no_provider_access_flags` | `execution_config.direct_provider_access=True` |
| `strategy_type_consistent` | Invalid StrategyType |

## 17. Experimental Strategies

`StrategyType.EXPERIMENTAL_PAPER` strategies:
- May proceed with `REQUIRES_REVIEW` status (not allowed for `VALIDATED_DEPLOYABLE`)
- Are always labeled explicitly in readiness reports
- Must never be confused with validated strategies (fingerprint differs)
- Require `permit_experimental=True` to pass readiness

## 18. Audit Trail

Every `StrategyEvaluation` is auditable: `evaluation_fingerprint` + `provenance` dict captures the complete lineage from snapshot through features, signals, targets, risk, and intents.

## 19. Failure Policies

| Failure | Behavior |
|---|---|
| `snapshot is None` | Raises `EvaluationError` |
| `snapshot.as_of is None` | Raises `EvaluationError` |
| PIT violation (feature as_of ≠ snapshot as_of) | Raises `EvaluationError` |
| NaN signal | Raises `EvaluationError` |
| Infinite signal | Raises `EvaluationError` |
| `compute_features()` returns None | Raises `EvaluationError` |
| `generate_signal()` returns None | Raises `EvaluationError` |
| Risk rejection | `risk_approved=False`, `ems_requests=[]`, warning in evaluation |
| Missing price for security | Security excluded from targets (no crash) |
| Invalid strategy type | `ReadinessValidator` rejects |

## 20. Limitations

1. **Strategy logic is user-supplied code** — M22 cannot verify that `StrategyLogic` implementations avoid look-ahead beyond enforcing `as_of` timestamp equality.
2. **In-memory registry** — `StrategyRegistry` does not persist to disk. Callers that need persistence must serialize via `spec.to_dict()`.
3. **Cost model passthrough** — `transaction_cost_assumption` is stored in the spec but not automatically passed to M14's cost models; the caller must wire this when constructing the EMS.
4. **FX** — Multi-currency portfolios require the caller to supply an M16 `FXRateProvider` in the snapshot; M22 does not configure FX automatically.
5. **Capacity model** — `capacity_assumption` is carried in the spec but not enforced by the runtime; M13's capacity checks apply if configured.

## 21. Future M23 Path

M23 should implement **Continuous Paper Trading & Forward Simulation Runtime**:
- A `PaperTradingLoop` that calls `StrategyRuntime.evaluate()` on each new `MarketDataSnapshot` from M20's live feed
- Persistent strategy state across evaluation cycles
- Automatic M12 session management
- Rebalance scheduling keyed to `spec.rebalance_frequency`
- Live drift monitoring between research expectations and paper performance
- Multi-strategy portfolio (multiple specs running concurrently)

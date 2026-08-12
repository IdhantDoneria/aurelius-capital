# AURELIUS M24 — Forward Paper-Trading Validation & Diagnostics Framework

## Purpose

M24 is an **observational-only** diagnostic layer that sits above M23 (Continuous Paper Trading).
It consumes M23 `ForwardPerformanceRecord` + M22 `StrategySpecification` + optional M9
`ValidationReport` and caller-supplied backtest results, then produces an immutable, fingerprinted
`ForwardValidationArtifact` and human/machine-readable `ForwardValidationReport`.

**M24 does NOT and cannot:**

- Promote, retire, or modify any strategy
- Change capital allocation, rebalance frequency, universe, or cost assumptions
- Create a second backtesting, paper-trading, risk, portfolio, or execution engine
- Fetch live market data from any external provider (no Bloomberg, Yahoo, FRED, SEC, NSE, BSE, etc.)
- Implement live-money execution
- Bypass M23

All diagnostic work is read-only. The only output is the validation artifact + report.

---

## Package location

```
src/aurelius/research/forward_validation/
    __init__.py            — public exports
    errors.py              — exception hierarchy
    models.py              — immutable domain models + enumerations
    statistics.py          — statistical computations (offline, stdlib only)
    drift.py               — drift detection
    data_diagnostics.py    — snapshot coverage + metadata diagnostics
    signal_diagnostics.py  — signal distribution analysis
    execution_diagnostics.py — fill rate + slippage diagnostics
    portfolio_diagnostics.py — weight drift diagnostics
    risk_diagnostics.py    — risk-rejection-rate diagnostics
    comparison.py          — backtest vs paper comparison + discrepancy classification
    attribution.py         — thin adapter over M11 simulation/attribution.py
    lineage.py             — lineage chain construction + validation
    report.py              — report assembly
    engine.py              — main orchestrator (ForwardValidationEngine)
```

---

## Core objects

### `ForwardValidationArtifact`
Frozen dataclass. Deterministically fingerprinted (blake2b, digest_size=16). Timestamps excluded
from fingerprint payload — same inputs always produce the same `artifact_fingerprint`.

Key fields:

| Field | Type | Description |
|---|---|---|
| `artifact_id` | str | blake2b of (strategy_id, version, fingerprints, n_cycles) |
| `strategy_id` | str | from M22 StrategySpecification |
| `strategy_fingerprint` | str | M22 fingerprint |
| `forward_record_fingerprint` | str | M23 ForwardPerformanceRecord fingerprint |
| `status` | str | ValidationStatus value |
| `operational_status` | str | OperationalStatus value |
| `economic_status` | str | EconomicStatus value |
| `sample_adequacy` | str | SampleAdequacy value |
| `metric_results` | dict | all diagnostic sub-sections |
| `diagnostic_results` | list | list[DiagnosticRecord.to_dict()] |
| `artifact_fingerprint` | str | computed by `stamp_artifact()` |

### `DiagnosticRecord`
Frozen dataclass. One finding. Machine-readable.

| Field | Type |
|---|---|
| `diagnostic_id` | str |
| `category` | str (DiscrepancyCategory value) |
| `severity` | str (DiagnosticSeverity value) |
| `metric` | str |
| `baseline` | float \| None |
| `observed` | float \| None |
| `difference` | float \| None |
| `threshold` | float \| None |
| `sample_size` | int |
| `method` | str |
| `evidence` | str |
| `status` | str (ValidationStatus value) |
| `fingerprint` | str |

### `ForwardValidationReport`
Frozen dataclass. Assembled from artifact by `assemble_report()`.

---

## Enumerations

All stored as plain string `.value` (Python 3.12-compatible; `str, Enum` `.value` used throughout).

| Enum | Values |
|---|---|
| `ValidationStatus` | INSUFFICIENT_DATA, IN_PROGRESS, VALID, WARNING, DIVERGENT, FAILED, INVALID |
| `OperationalStatus` | OPERATIONALLY_VALID, OPERATIONALLY_INVALID, OPERATIONALLY_INCONCLUSIVE |
| `EconomicStatus` | ECONOMICALLY_CONCLUSIVE, ECONOMICALLY_INCONCLUSIVE |
| `SampleAdequacy` | INSUFFICIENT (<20), PRELIMINARY (20-62), MEANINGFUL (63-251), EXTENDED (≥252) |
| `DiscrepancyCategory` | DATA_DRIFT, SIGNAL_DRIFT, UNIVERSE_DRIFT, PORTFOLIO_DRIFT, EXECUTION_DRIFT, COST_DRIFT, RISK_DRIFT, ACCOUNTING_DRIFT, TIMING_DRIFT, IMPLEMENTATION_DIVERGENCE, STATISTICAL_NOISE, INSUFFICIENT_SAMPLE, UNKNOWN |
| `DiagnosticSeverity` | INFO, WARNING, ERROR, CRITICAL |

---

## Diagnostic modules

### Data diagnostics (`data_diagnostics.py`)
- `analyze_snapshot_coverage`: gap/duplicate/ordering detection from cycle dates
- `analyze_snapshot_metadata`: stale snapshots, source-change detection, missing fields
- Produces DATA_DRIFT records for ordering errors, duplicates, staleness, provenance changes

### Signal diagnostics (`signal_diagnostics.py`)
- `analyze_signal_distribution`: mean, stdev, coverage from signal_history
- `compare_signal_distributions`: compares research baseline vs forward distribution

### Execution diagnostics (`execution_diagnostics.py`)
- Fill-rate deviation from expected
- Slippage proxy vs spec_slippage_bps

### Portfolio diagnostics (`portfolio_diagnostics.py`)
- Weight drift vs weight_history baseline

### Risk diagnostics (`risk_diagnostics.py`)
- Risk-approval-rate deviation from expected

### Comparison (`comparison.py`)
- `build_comparison`: tabular backtest vs paper metric comparison (total_return, sharpe, max_drawdown, volatility, fill_rate)
- `classify_discrepancies`: collects DiscrepancyCategory values present in diagnostics; always adds INSUFFICIENT_SAMPLE when sample is INSUFFICIENT or PRELIMINARY

### Drift detection (`drift.py`)
- `detect_metric_drift`: generic threshold-based drift (relative or absolute)
- `execution_drift`, `cost_drift`, `risk_drift`, `signal_drift`: specialized detectors
- `detect_pit_violation`: CRITICAL if signal_date > snapshot_date (look-ahead bias)
- `detect_snapshot_ordering`: ERROR if snapshots arrive out of order

### Attribution (`attribution.py`)
Thin adapter over `aurelius.research.simulation.attribution`. Does NOT re-implement P&L logic.

### Lineage (`lineage.py`)
`LineageChain` — links research artifact → validation artifact → strategy version → deployment
manifest → forward record. Verified deterministically via fingerprints.

---

## Engine (`engine.py`)

`ForwardValidationEngine.analyze(forward_record, spec, ...)` orchestrator:

1. Build lineage chain
2. Cycle date / data diagnostics
3. Snapshot ordering / PIT checks
4. Signal diagnostics
5. Execution diagnostics
6. Portfolio diagnostics
7. Risk diagnostics
8. Performance metrics (annualized, rolling, bootstrap CI)
9. Backtest comparison
10. Drift detection
11. Aggregate all DiagnosticRecords
12. Determine status (INSUFFICIENT_DATA / INVALID / FAILED / DIVERGENT / WARNING / VALID)
13. Determine operational status
14. Determine economic status
15. Classify discrepancies (stored in `metric_results["discrepancies"]`)
16. Stamp artifact (deterministic fingerprint)

### Status determination logic

```
n < 20                          → INSUFFICIENT_DATA
has_critical                    → INVALID
has_error                       → FAILED
has_drift and backtest provided → DIVERGENT
has_warning                     → WARNING
else                            → VALID
```

### Operational status
```
has_critical or has_error → OPERATIONALLY_INVALID
n < 20                    → OPERATIONALLY_INCONCLUSIVE
else                      → OPERATIONALLY_VALID
```

### Economic status
```
adequacy in (MEANINGFUL, EXTENDED) and ann.reliable → ECONOMICALLY_CONCLUSIVE
else                                                 → ECONOMICALLY_INCONCLUSIVE
```

---

## Statistical computations (`statistics.py`)

All offline, stdlib only (no numpy, no network):

- `sample_adequacy(n)` → SampleAdequacy enum
- `compute_annualized(nav_series)` → AnnualizedMetrics (return, volatility, sharpe, sortino, max_drawdown, reliable flag)
- `rolling_sharpe`, `rolling_volatility`, `rolling_drawdown` — only when len ≥ rolling_window
- `bootstrap_mean_ci(values, n_samples=500, alpha=0.05, seed=0)` — deterministic, non-parametric
- `return_distribution_summary(daily_rets)` — n, mean, stdev, min, max, p25, p50, p75, skewness, kurtosis

---

## Fingerprinting

blake2b, digest_size=16 — same as M7/M22/M23. `_fp(obj)` in `models.py`.

Fingerprint payload excludes timestamps (`recorded_at`, `created_at`, etc.) so the same analysis
inputs always produce the same `artifact_fingerprint`.

`_ev(x)` helper: `x.value if hasattr(x, 'value') else str(x)` — fixes Python 3.12 enum str()
representation (`str(SomeEnum.MEMBER)` returns "SomeEnum.MEMBER", not "MEMBER").
All enums stored as plain `.value` strings throughout.

---

## Tests

`tests/research/test_forward_validation.py` — **117 tests**, all offline, all passing.

Test classes:
- `TestSampleAdequacy` — boundary conditions
- `TestComputeAnnualized` — annualized metrics
- `TestRollingMetrics` — rolling sharpe/volatility
- `TestBootstrapCI` — CI bounds + determinism
- `TestReturnDistribution` — distribution summary
- `TestDataDiagnostics` — coverage, ordering, staleness
- `TestSignalDiagnostics` — distribution analysis, comparison
- `TestDriftDetection` — metric drift, execution/cost/risk drift, signal drift, PIT violation
- `TestMakeValidationArtifact` — frozen, fingerprint verification
- `TestBuildComparison` — backtest comparison table
- `TestClassifyDiscrepancies` — discrepancy classification
- `TestLineageChain` — lineage construction + fingerprint
- `TestAssembleReport` — report assembly from artifact
- `TestEndToEndCertification` — 12 end-to-end certification scenarios (a–l):
  - a: healthy strategy, extended sample
  - b: healthy strategy, preliminary sample
  - c: execution drift detected
  - d: PIT violation → INVALID
  - e: data ordering violation
  - f: risk rejection drift
  - g: backtest divergence
  - h: no backtest
  - i: insufficient sample → INSUFFICIENT_SAMPLE discrepancy
  - j: fingerprint reproducibility
  - k: artifact round-trip serialization
  - l: missing forward metrics

---

## Security constraints

- No secrets or credentials stored
- Tests run without network access
- No external data providers called from M24
- Observational only — no automated decisions, mutations, or promotions

---

## Known limitations

- Rolling metrics not computed when `len(daily_rets) < rolling_window` (by design)
- Bootstrap CI uses stdlib `random` (no numpy) — suitable for offline diagnostic use, not publication-grade
- Backtest comparison requires caller-supplied backtest metrics dict; M24 does not re-run backtests
- Attribution requires M11 `aurelius.research.simulation.attribution`; if unavailable, `forward_attribution` returns `analyzed=False`
- No annualized statistics claimed for INSUFFICIENT/PRELIMINARY samples (`ann.reliable = False`)
- Corporate action replay through checkpoint not serialized (M15 limitation)
- Partial-fill simulation uses SimulatedBroker fill_ratio without real ADV data
- No intraday scheduling (day-granular only)

---

## Lineage

```
research_artifact (M7)
  └─ validation_artifact (M9)
       └─ strategy_version (M22)
            └─ deployment_manifest (M22)
                 └─ forward_record (M23)
                      └─ M24 ForwardValidationArtifact
```

---

## M25 recommendation discipline

M24 produces findings. It does NOT recommend any operational action automatically.
Any decision (promote/retire/adjust/hold) requires explicit human review of the
`ForwardValidationReport`. M25 planning begins after M24 certification.

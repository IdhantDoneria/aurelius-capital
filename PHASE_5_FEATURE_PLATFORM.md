# Phase 5 — Institutional Feature Engineering Platform

**Status:** 139/139 tests pass (126 prior + 13 new). Ruff clean. Package: `src/mentisrex/features/`.

A reusable feature ecosystem: features are defined once, documented, versioned,
and reused across every model and backtest — never recomputed inline in a strategy.

## Data flow

```
Market Data (OHLCV bars, Decimal)
      │
      ▼
Feature Library ──register──► Feature Registry (metadata: formula, inputs,
  (pure fns / category)        version, owner, quant docs, validation status)
      │
      ▼
Feature Pipeline (rolling window per bar → look-ahead safe;
                  batch + incremental via cache; None on missing)
      │
      ▼
Feature Store (DuckDB: definitions + point-in-time values)
      │
      ▼
Strategy Models  →  Backtesting Engine (Phase 4, untouched)
```

## Components

| File | Responsibility |
|---|---|
| `registry.py` | `FeatureSpec` (metadata), `Window`, `Bar`, `@feature` decorator, `REGISTRY`, lookup + math helpers |
| `library/{price,volatility,statistical,volume,technical}.py` | 18 features as pure `Window -> Decimal \| None` functions |
| `pipeline.py` | `FeaturePipeline`: windowing, look-ahead enforcement, cache, incremental, error isolation |
| `store.py` | `FeatureStore`: DuckDB persistence of definitions + point-in-time values |
| `tests/features/test_features.py` | value correctness, look-ahead invariance, cache, store round-trip |

## Features (18)

- **Price (5):** returns_1d, log_returns_1d, sma_20, momentum_21d, trend_strength_20
- **Volatility (3):** hist_vol_20, rolling_std_20, atr_14
- **Statistical (4):** zscore_20, mean_deviation_20, correlation_60, beta_60
- **Volume (3):** volume_change_1d, relative_volume_20, volume_anomaly_20
- **Technical (3):** rsi_14, macd_hist, bollinger_pctb_20

Every feature carries mandatory quant docs: economic intuition, expected
behaviour, failure modes, validation methodology (enforced by a test).

## Bias prevention

- **Look-ahead:** the pipeline builds each bar's `Window` from bars `[..t]` only —
  structurally impossible to read the future. Tested by appending future bars and
  asserting past values are unchanged.
- **Data leakage:** all statistics (z-score, correlation, beta, bands) use a
  *trailing* window; the benchmark for beta/correlation is aligned by timestamp,
  and if coverage is partial the feature emits `None` rather than a misaligned number.
- **Survivorship:** the pipeline never invents symbols — the caller supplies the
  point-in-time universe. On read, `FeatureStore` clips to `timestamp <= as_of`.

## How researchers add a feature

1. Write a pure function in the matching `library/*.py`:
   ```python
   @feature(
       name="my_signal", category=Category.PRICE, version=1,
       description="...", formula="...", inputs=("close",),
       min_periods=30, owner="you", status=ValidationStatus.EXPERIMENTAL,
       economic_intuition="...", expected_behavior="...",
       failure_modes="...", validation_method="...",
   )
   def my_signal(w: Window) -> Decimal | None:
       if len(w) < 30:
           return None
       ...
   ```
2. Add a test asserting a known value + a look-ahead check.
3. `FeatureStore.sync_definitions(all_features())` persists the new spec.

No pipeline or store change is needed — registration is automatic on import.

## Version control

`(name, version)` is the identity everywhere: registry key `name@vN`, the
`feature_definitions` PK, and part of the `feature_values` PK. To change a
feature's math, **bump `version`** and add a new function — never edit the old
one. Old values stay reproducible; both versions coexist. `get(name)` returns
the highest version; `get(name, version=1)` pins one.

## How computation scales

- Per-bar cost is bounded to O(max_lookback), not O(history): the pipeline slices
  a trailing window of `max(min_periods)+1` bars. `ponytail:` recompute-per-bar is
  the deliberate ceiling — swap to streaming EMA/rolling state if a full
  3000×200 nightly job gets slow.
- Incremental runs (`since=`) plus the `(symbol, feature, version, ts)` cache skip
  already-computed values.
- DuckDB is the fast columnar read layer (same pattern as `market_data` OHLCV);
  PostgreSQL `research.FeatureDefinition` / `FeatureValue` remain authoritative and
  already support monthly partitioning for 150M+ rows/year.

## Known scope notes

- Persistence reuses the **existing** Phase-2 Postgres schema (`research.py`) — the
  brief's four table names map onto `feature_definitions` + `feature_values`; no new
  Postgres tables were added. The new DuckDB store is the research replica.
- `PHASE_5_CONSTRAINTS.md` is referenced by the quick-ref but does not exist in the repo.
- mypy-strict is not this repo's gate (the pre-existing code has 47 strict errors);
  the enforced bar is ruff + pytest, which Phase 5 meets.

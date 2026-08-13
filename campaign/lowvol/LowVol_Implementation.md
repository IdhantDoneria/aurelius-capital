# Low-Volatility Factor — Implementation (M12 Phase 2)

**Date:** 2026-08-05. New factor family; certified `FactorStrategy` untouched.

## 1. What was built

`LowVolStrategy` in `src/mentisrex/research/templates.py` — a NEW strategy class
(ALLOWED: new factor implementation). It reuses the certified construction *standards*
via the shared modules but never modifies certified code:
- M1 equal-weight leg budget, M2 `$5` price screen,
- M7 liquidity framework (`liquidity.py`), M8 bounded invariant construction
  (`portfolio_construction.invariant_weight`).

## 2. Baseline volatility measure (chosen)

**Trailing standard deviation of daily simple returns over `lookback` bars**
(`statistics.pstdev` of `c[i]/c[i-1]-1`). This is the standard **total-volatility**
estimator (Haugen-Baker, Blitz-van Vliet, BAB), reproducible on the price-only panel.

Candidates considered (per directive):
- *rolling daily standard deviation* → **chosen baseline** (standard, price-only).
- *realized volatility* → at daily frequency this is the same estimator (sum/stdev of
  daily returns); no separate intraday data to justify a distinct measure.
- *downside volatility* (semi-deviation of negative returns) → retained as a **Phase-5
  robustness estimator** (`downside=True`), not the baseline.

## 3. Factor output / ranking

Every eligible stock gets a volatility score = trailing stdev. **Lower volatility →
higher rank → LONG**; highest-volatility decile → SHORT. This is the opposite tail
sense to momentum (which longs high scores); implemented by assigning LONG to
`val <= lo` (bottom decile) and SHORT to `val >= hi` (top decile).

## 4. Baseline parameters (pre-registered, not tuned)

```
LowVolStrategy(lookback=252, quantile=0.10, rebalance_days=21,
               allow_short=True, equal_weight=True, min_price=5.0,
               invariant_construction=True)     # M8 standard
max_position_pct=1.0
```

- `lookback=252` (1-yr), `quantile=0.10` (decile), `rebalance_days=21` (monthly) —
  single literature-standard values, no sweep (sweeps are Phase-5 robustness only).
- `invariant_construction=True` — the M8-mandated standard for any run (inert at full
  universe, protective when Phase-5/7 shrink it).

## 5. Compliance

- No modification to data pipeline, reporting, certified construction, execution
  engine, or benchmark. New class + new params only.
- Look-ahead-free: score at `t` uses `ctx.history` (bars ≤ t). Deterministic (pure
  function of history). Both asserted in
  `test_lowvol_ranks_low_vol_long_and_is_deterministic`.
- 598 passed, 2 skipped after adding the factor + test.

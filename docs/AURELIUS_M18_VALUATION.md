# AIDP M18 — Institutional Valuation & Market-Data Infrastructure

**Commit:** `0d910ae`

## What this is

One canonical, deterministic, point-in-time valuation architecture that supplies market
inputs and theoretical values to the whole platform (M10 construction, M11 simulation,
M12 paper, M13 risk, M14 execution, M15 post-trade, M16 FX, M17 multi-asset accounting).
It is **not** a collection of pricing formulas bolted together — the primary deliverable is
a reusable valuation *infrastructure* with governed models and injected market data.

M17 deliberately left valuation providers as extension points; **M18 fills them** with
production-quality implementations.

### Package

`src/aurelius/research/valuation/` — 24 modules.

## Core architectural rule

Every valuation is reproducible from exactly four things:

```
Instrument  +  MarketDataSnapshot  +  ValuationDate  +  ValuationConfiguration
```

The engine **never silently fetches live data** — the `MarketDataSnapshot` is injected,
immutable, and provenance-stamped. A `ValuationResult` carries model name/version and an
input fingerprint + market-data fingerprint, so any number can be reproduced and audited.

## Architecture / decisions

- **Snapshot, not feed.** Valuation consumes an immutable snapshot; providers *build*
  snapshots. This makes look-ahead structurally impossible inside the engine.
- **Reuse, don't fork.** FX is the injected M16 `FXRateProvider` (never re-implemented); the
  instrument model is M17's `Instrument`; risk stays M13's job — M18 only supplies
  sensitivities.
- **Governed models.** Every result names a `model@version` declared in a `ModelRegistry`.
- **Determinism first.** Closed-form where possible, fixed-step binomial for American,
  bisection for root-finds — no randomness that isn't seeded, no wall-clock.

## Market-data architecture

`MarketDataSnapshot` (frozen) holds spots, quotes (bid/ask/volume), dividend yields, forwards,
yield curves (`ZeroCurve`/`DiscountCurve`), volatility surfaces, corporate-action assumptions,
an injected M16 FX provider, `as_of` valuation date and `Provenance`. Typed accessors
(`spot`, `dividend_yield`, `curve`, `vol_surface`, `fx_rate`) raise on missing data rather
than silently defaulting. `MarketDataProvider` (ABC) has `StaticMarketDataProvider`,
`HistoricalMarketDataProvider` (PIT — last observation on/before the date),
`DeterministicMockMarketDataProvider` (offline tests/benchmarks) and the abstract
`ProductionMarketDataAdapter` interface a real feed would implement. No network anywhere.

## PIT guarantees

Every datum carries `source`, `observation_date`, `effective_date`, `timestamp`, `currency`,
`instrument_id`. `snapshot.validate_pit` rejects: observations dated after the valuation date
(look-ahead), missing valuation dates, data staler than a configured tolerance, and
timestamp/observation-date inconsistencies. The engine runs this gate before valuing (unless
explicitly disabled for batch, where it is validated once).

## Curve infrastructure

`ZeroCurve` (linear in zero-rate space), `DiscountCurve` (log-linear in DF — piecewise-flat
forwards), `ForwardCurve`. Discount factor, zero rate, forward rate; injected day-count
(ACT/365, ACT/360, 30/360, ACT/ACT) and compounding (continuous, simple, annual, semiannual).
Invariants validated: DF(0)=1, DF(T)>0, strictly increasing tenors, monotone-DF diagnostic.
`CurveBuilder` builds a curve from nodes and returns a `CurveCalibrationReport` +
`CalibrationDiagnostics`; conventions are injected, not assumed universal.

## Volatility infrastructure

`VolatilitySurface` — implied vol over (strike, maturity), bilinearly interpolated, immutable,
staleness-checked. `flat_surface` for the single-vol case; `ConstantVolProvider` /
`SurfaceVolProvider` implement a `VolatilityProvider`. Calendar-spread (total-variance
monotonicity) and non-positive-vol diagnostics.

## Pricing models

- **Black-Scholes** (spot + continuous dividend yield) — European calls/puts.
- **Black-76** (option on a forward/future) — equals BS with S→F, q→r (tested).
- **Binomial CRR** (`american.py`) — real early-exercise American options, deterministic
  fixed-step, converges to BS for European payoffs.
- **Futures/forwards** — cost-of-carry fair value F = S·e^{(r−q)T}, basis, implied financing,
  expiry convergence.
- **Bonds** — clean/dirty price, accrued interest, coupon cash flows, YTM, Macaulay & modified
  duration, convexity, DV01, curve DCF. Period-index (actual/actual ICMA) discounting so a
  bond yielding its coupon prices exactly at par.
- **Swaps** — single/dual-curve IRS: fixed & floating leg PV, NPV, par rate, DV01, cash-flow
  projection.
- **Cross-currency swaps** — two legs, two curves, translated to base via the M16 FX provider.
- **FX** — spot/forward (covered interest parity), forward points, cross rate, FX-forward value.

Validated no-arbitrage behaviour: put-call parity, call/put monotonicity, positive-time value,
expiry intrinsic, European bounds (`diagnostics.option_bounds`).

## Greeks

Delta, gamma, theta, vega, rho, plus vanna and volga interfaces — all derived from the same
pricing inputs. `greeks.py` provides finite-difference cross-checks used by the numerical
tests (analytic vs FD agree to 1e-3–1e-5). American Greeks by finite difference on the tree.

## Multi-asset valuation

`ValuationEngine.value(instrument, snapshot, config)` dispatches by M17 `InstrumentType` and
returns a governed `ValuationResult` (price, market value, base value, P&L, Greeks,
model/version, fingerprints, assumptions, diagnostics). `PortfolioValuationEngine` values a
heterogeneous book (equities, futures, options, bonds, forwards, swaps, cash/collateral/margin
via M17) and returns gross/net/base value, unrealized P&L, aggregated Greeks and the
sensitivity inputs M13 consumes. Swaps and cross-currency swaps have dedicated entry points
(`value_swap`, `value_cross_currency`) because they need explicit schedule specs.

## M16 / M17 integration

- **M16:** `MarketDataSnapshot.fx_rate` and all cross-currency valuation call the injected
  `FXRateProvider` — FX conversion is not duplicated. Reciprocal consistency is a diagnostic.
- **M17:** `adapters.M18Pricer` implements the M17 `PricingProvider`/`GreeksProvider` and
  `adapters.M18YieldProvider` implements `YieldProvider`, so an M17 `InstrumentBook` requests
  real price / NPV / Greeks / yield / duration from M18 with **no M17 code change** (tested:
  M17 risk consumes M18 Greeks).

## M13 risk integration

`greeks.to_m13_risk_inputs` and `PortfolioValuation.risk_inputs` shape portfolio value, delta,
gamma, vega, rho, duration, DV01, FX exposure and margin requirement into M13's input dict.
M18 supplies valuation and sensitivities; **M13 remains the risk authority** — no VaR, no
limits, no covariance here.

## Model governance

`ModelRegistry` / `default_registry` declare every shipped model with a version and its
assumptions. Each `ValuationResult` stamps `model_name`, `model_version`, `input_fingerprint`,
`market_data_fingerprint` and exposes a `reproducible_key`. A valuation is reproducible by
construction.

## Tests

`tests/research/test_valuation.py` — **171 deterministic, offline tests**. Cover day-count/
compounding, interpolation, curves + discounting + forward curves, curve building, vol
surfaces, Black-Scholes, Black-76, Greeks (analytic vs finite-difference), implied vol,
American binomial, futures, bonds, swaps, FX, cross-currency swaps, snapshots + PIT, providers,
the engine (all asset classes), portfolio valuation, governance, determinism/property
invariants, arbitrage diagnostics, validation, reconciliation and M16/M17 integration.

Full suite: **1501 passed, 3 skipped** (pre-existing) — zero M1–M17 regressions.

## Benchmarks

`scripts/benchmark_m18_valuation.py` (deterministic, offline). Representative run:

| instruments | single valuation | batch (portfolio) | throughput | curve build | surface interp | peak |
|-------------|------------------|-------------------|------------|-------------|----------------|------|
| 1,000       | ~94 µs           | 0.2 s             | ~5,000/s   | ~28 µs      | ~10 µs         | 1 MB |
| 10,000      | ~97 µs           | 2.0 s             | ~5,050/s   | ~29 µs      | ~10 µs         | 8 MB |
| 100,000     | ~103 µs          | 19.9 s            | ~5,010/s   | ~28 µs      | ~11 µs         | 79 MB|

Swap NPV ~24 µs each. 100k = 25k × 4 asset classes. Numbers are machine-dependent; scaling is
linear (immutable-snapshot fingerprint is memoized).

## Numerical validation

Verified against analytical identities with deterministic tolerances: put-call parity (BS &
Black-76), Black-76 = BS at q=r, analytic Greeks vs finite differences, implied-vol round-trip,
American ≥ European (and → European without early exercise), bond par-at-coupon, YTM
round-trip, DV01 ≈ modified-duration·price·1bp, futures expiry convergence & implied-financing
round-trip, FX reciprocal consistency, swap par-rate zeroes NPV, portfolio sum-of-parts.

## Backward compatibility

M18 is **purely additive** — it creates a new package and a new test file and modifies **no
M1–M17 source**. Full repository suite: 1501 passed, 3 pre-existing skips, zero regressions.

## Known limitations / Skipped

Each is a bounded interface with a stated unblock — no silent omission.

- **Production market-data feed.** `ProductionMarketDataAdapter` is an abstract interface; M18
  ships no live feed. Reason: deterministic/offline mandate. Unblock: implement the adapter
  against a real provider, returning an immutable PIT-tagged snapshot.
- **Multi-instrument curve bootstrap.** `CurveBuilder.build_zero` takes zero nodes directly;
  full bootstrap from deposits/FRAs/futures/swaps with convention handling is an interface.
  Reason: bootstrap conventions are market/desk-specific and must be injected. Unblock: a
  convention-parameterised solver behind the existing `CurveCalibrationReport`.
- **Vol-surface calibration / SABR / smile models.** Surfaces are interpolated from a supplied
  grid; no model-fit calibration. Reason: scope. Unblock: a surface-calibration provider.
- **American exercise granularity.** CRR is a discrete Bermudan approximation; accuracy is
  `steps`-limited (documented in `american.py`). Unblock: adaptive/finite-difference PDE solver.
- **Business-day calendars & holiday roll.** Day-count is calendar-free; no holiday adjustment.
  Reason: calendar data not in scope. Unblock: inject a holiday calendar into schedule building.
- **Credit / OIS-discount / multi-curve basis.** Bonds use a single discount curve, no credit
  spread; swaps are single/dual-curve without explicit basis. Unblock: add spread/basis curves
  to the snapshot and discount accordingly.

## Future production data feeds

Live market-data adapters (implementing `ProductionMarketDataAdapter`), real curve
bootstrapping with injected conventions, calibrated vol surfaces (SABR/SVI), OIS/multi-curve
discounting, credit spreads, and business-day calendars — all slot into the existing injected
interfaces without touching the engine.

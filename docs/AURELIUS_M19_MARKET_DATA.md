# AIDP M19 — Institutional Market Data, Curve Calibration & Volatility Surface Engine

**Commit:** `1db2035`

## What this is

The market-data infrastructure that sits **underneath** M18. M18 values instruments from an
injected, immutable `MarketDataSnapshot` but does not build one from raw market observations. M19
is that missing layer:

```
Sources → Raw records → Normalization → Quality → PIT → Canonical observations
    → Curve calibration + Volatility calibration → M18 MarketDataSnapshot
    → M18 valuation → M13 risk / M14 execution / M15 post-trade
```

The same canonical interfaces serve historical, delayed, live, deterministic-test and vendor data.
M19 **produces M18 objects** (`ZeroCurve`, `DiscountCurve`, `VolatilitySurface`,
`MarketDataSnapshot`) — it does not duplicate the valuation engine, the M16 FX book, or the M13
risk engine. It addresses **all six** M18 deferred items.

### Package

`src/mentisrex/research/market_data/` — 23 modules.

## 1. Architecture

A one-way pipeline of small, injectable, immutable pieces. Each stage is a pure function of its
inputs; nothing holds mutable market state; nothing calls the network. `MarketDataEngine` is the
façade wiring the pieces:

    models · identifiers · calendars · revisions · fixings          (foundations)
    sources · normalization · quality · diagnostics                 (ingest + integrity)
    rate_instruments · bootstrap · multicurve · credit              (rate/credit curves)
    sabr · svi · vol_calibration                                    (volatility)
    pit · validation · serialization · registry · adapters · engine (assembly + governance)

## 2. Canonical market-data model (`models.py`)

`CanonicalObservation` is the single typed datum — never a bare float. Fields: `security_id`,
`obs_type` (`ObservationType`: trade/quote/close/adjusted_close/corporate_action/dividend/split/
fx_rate/interest_rate/yield/discount_factor/forward/volatility/volume/open_interest/reference),
`field`, `value`, `observation_date` (knowable), `effective_date` (for), `source`, `timestamp`,
`currency`, `unit` (`Unit`: price/rate/percent/basis_point/factor/vol/…), `status`
(`QualityStatus`), `revision`, `meta`. It carries an M18 `Provenance` and a deterministic
`fingerprint`. `QualityDiagnostic` is the structured finding (code/severity/message). Semantics
stay explicit — a rate is never confused with a price.

## 3. Provider / source model (`sources.py`, `providers` seam)

`MarketDataSource` (ABC) yields **raw** records for a valuation date: `StaticSource`,
`HistoricalSource` (PIT — only records knowable on/before `as_of`), `DeterministicMockSource`.
This is deliberately separate from M18's `MarketDataProvider`, which yields a *finished* snapshot:
sources hold messy external schemas, providers expose the clean contract the engine sees. Every
source is offline and deterministic.

## 4. Normalization (`normalization.py`)

`Normalizer.normalize(raw, as_of)` runs an auditable sequence — schema validation → identifier
normalization (PIT via `IdentifierMap`) → unit normalization (percent/bp → decimal rate) →
currency normalization (optional M16-FX conversion) → timestamp/date normalization →
duplicate/revision resolution (highest revision wins, ties by latest observation) — returning a
`NormalizationResult` (observations + structured diagnostics + a transform log). It never silently
coerces: a malformed record yields a diagnostic, not a guess. Handled: duplicates, revisions,
missing values, non-numeric values, missing id/field, currency mismatch, timestamp inconsistency.

## 5. Identifier system (`identifiers.py`)

Ticker ≠ security identity. `IdentifierMap` resolves external ids (ticker/exchange_ticker/ISIN/
CUSIP/FIGI/Bloomberg/vendor) to a stable internal `security_id`, **PIT-aware** (a resolution is
only valid within its effective window, because tickers are reused over time). It refuses to
collapse two instruments onto one security: `add` rejects an overlapping collision and `resolve`
raises on an ambiguous match rather than guessing.

## 6. PIT guarantees (`pit.py`)

`MarketDataSnapshotBuilder` builds the snapshot **correctly**, so M18's PIT validator has nothing
to catch: raw → normalize → quality → PIT enforcement → assemble → M18 `validate_pit`. Any
observation dated after the valuation date is a REJECT before assembly and re-checked by M18, so
look-ahead is structurally impossible. It is **fail-closed** on valuation-critical data (a rejected
spot raises `SnapshotBuildError`) and warning-only on the rest. Output is an immutable M18
`MarketDataSnapshot` with provenance and a fingerprint.

## 7. Revision / restatement handling (`revisions.py`)

`RevisionStore` is append-only and bitemporal, separating two questions: `known_as_of(effective,
knowledge)` — "what did we *know* then?" (PIT-safe, uses only revisions published by the knowledge
date) — from `current(effective)` — "what is the latest *revised* value?" (look-ahead; reporting
only). A restatement adds a new record; the original survives for audit. This is the guardrail for
future fundamental/macro research where first-print vs revised matters.

## 8. Data provenance (`models.py` + M18 `Provenance`)

Every canonical observation reproduces its M18 `Provenance` (source, observation_date,
effective_date, timestamp, currency, instrument_id) and carries a `revision` and a `fingerprint`.
Curves, surfaces and snapshots each carry their own fingerprint, so any produced artifact is
traceable to its inputs and reproducible.

## 9. Data-quality engine (`quality.py`, `diagnostics.py`)

`MarketDataQualityEngine.check` classifies observations and returns **structured diagnostics** —
it never repairs. Severities: `INFO/WARNING/ERROR/REJECT`; observations tripping a REJECT (or, if
configured, ERROR) rule are partitioned into `rejected` and never valued. Checks: look-ahead
(REJECT), staleness (WARNING), non-positive price (REJECT), crossed quote (REJECT), wide spread
(WARNING), bad OHLC (REJECT), negative volume (ERROR), price jump (WARNING), missing/NaN (REJECT).
`diagnostics.py` adds the microstructure/OHLC checks and **re-exports** M18's arbitrage diagnostics
(curve DF positivity, FX reciprocal, calendar-spread) rather than re-implementing them.

## 10. Business-day calendar engine (`calendars.py`)

`BusinessCalendar` (ABC) with `WeekendCalendar`, `HolidayCalendar` (injected holiday sets),
`JointCalendar` (union of centers). Roll conventions following / modified_following / preceding /
modified_preceding / none; `add_business_days`, `business_days_between`, `adjust`. All arithmetic
routes through `numpy.busday_*` (the mechanism M15 settlement uses) so dates are deterministic.
Sample US/UK/India holiday sets 2024-2026 are provided and **injectable**; exhaustive vendor
holiday history is out of scope (see limitations). Calendars are meant to be injected into
schedule building — no valuation module hard-codes an exchange's holidays.

## 11. Rate instruments (`rate_instruments.py`)

Canonical `RateInstrument` (`InstrumentKind`: deposit/ois/fra/future/swap/gov_bond/basis_swap) with
tenor/start/quote and an **injected** `RateConvention` (day-count, compounding, payment frequency,
settlement lag, calendar). Futures carry a price and expose `implied_rate` = (100−price)/100.
Convenience constructors: `deposit`, `ois`, `fra`, `rate_future`, `swap`.

## 12. Curve bootstrapping (`bootstrap.py`)

`CurveBootstrapper.bootstrap` — the M18 deferred multi-instrument bootstrap. Instruments are sorted
by maturity; each node's zero rate is solved by deterministic sign-agnostic **bisection** so that
instrument reprices to its quote given the already-built short end. Output is a reused M18
`ZeroCurve` plus a `CurveCalibrationReport` carrying per-instrument repricing residuals. A curve
that fails to reprice within tolerance is reported not-ok and, in strict mode, raises — never
silently accepted. Measured max repricing residual across deposits/FRAs/futures/swaps: **< 1e-12**.

## 13. OIS / multi-curve (`multicurve.py`)

`MultiCurveSet` = a discount curve + optional projection/forecast curve + named basis curves, all
M18 `ZeroCurve`s. Discounting uses the discount curve; forward rates project off the projection
curve. Generic — **no index (SOFR/ESTR/EURIBOR) is hard-coded**; you inject bootstrapped curves and
label them. `single_curve` and `ois_multicurve` helpers.

## 14. Credit curves (`credit.py`)

`CreditCurve` carries a piecewise-constant hazard term structure and derives survival / default
probability / approximate par spread. `bootstrap_credit` calibrates hazards from par CDS spreads by
sequential bootstrap against an injected discount curve — one hazard node per maturity, each solved
so the CDS prices to zero on a discrete premium grid. Survival is monotone non-increasing; hazards
are constrained ≥ 0. Measured CDS repricing residual: **< 1e-7**. This is a deterministic bootstrap
interface, not a full ISDA CDS pricer (see limitations).

## 15. Volatility calibration (`vol_calibration.py`)

`VolatilitySurfaceCalibrator` calibrates each expiry's smile with a DI-selected model — SABR, SVI,
or interpolated — and **materializes an M18 `VolatilitySurface`** (a strike×maturity grid) so every
M18 consumer works unchanged. It is bid/ask-aware (fits mids, flags fitted vols outside the quoted
spread) and runs arbitrage diagnostics. `CalibratedVolProvider` implements the M18
`VolatilityProvider` protocol directly from the parametric smiles (interpolating in total variance
across expiries) — the exact interface the M18 option pricer consumes.

## 16. SABR (`sabr.py`)

Hagan (2002) lognormal implied-vol expansion plus a deterministic calibrator: β is fixed (market
choice), (α, ρ, ν) fit by a deterministic (ρ, ν) grid with α pinned to the ATM vol by 1-D
bisection, then a local refinement grid. Parameters validated (α>0, β∈[0,1], |ρ|<1, ν>0); invalid
combinations are never returned. On a smile generated from known parameters, calibration recovers
them to **< 1e-6**.

## 17. SVI (`svi.py`)

Gatheral raw SVI total-variance parameterization. For fixed (m, σ) the model is linear in
(a, b·ρ, b), so each grid node is a closed-form least-squares solve; a deterministic (m, σ) grid
selects the best. Parameters validated; Gatheral–Durrleman g(k) ≥ 0 is the butterfly (static)
no-arbitrage check. Measured fit residual on a SABR-generated smile: **< 1e-3 total variance**, no
butterfly arbitrage.

## 18. Arbitrage diagnostics

Volatility: negative variance, per-smile butterfly (SVI Durrleman g), calendar-spread monotonicity
across expiries (reusing M18's `calendar_spread`), non-positive vol. Curves: DF positivity,
non-monotone DF (negative forwards), zero-rate discontinuity. FX: reciprocal consistency (M18). A
surface is not labelled arbitrage-free without these checks passing; the surface calibration report
is `ok` only when they do.

## 19. M16 integration

FX is **not** duplicated. The normalizer's optional currency conversion and every FX rate on a
built snapshot call the injected M16 `FXRateProvider` (`rate(base, quote, as_of=)`). Reciprocal
consistency is a diagnostic. M16 remains responsible for currency accounting and FX P&L; M19 only
supplies the underlying observations/rates.

## 20. M17 integration

M19-calibrated vol surfaces and curves feed M17 instruments through M18's existing provider seams
with no M17 change: a materialized `VolatilitySurface` drops into `snap.vol_surfaces`, and
`CalibratedVolProvider` satisfies the `implied_vol(instrument_id, strike, maturity)` protocol M18
(and thus M17 option accounting) already consumes. Tested: an M19 surface prices an M17 option
through the M18 engine.

## 21. M18 integration

The dependency is **M19 market data → M18 valuation**, not two valuation engines. M19 bootstraps
M18 `ZeroCurve`s, calibrates M18 `VolatilitySurface`s, and assembles an M18 `MarketDataSnapshot`;
the M18 `ValuationEngine`/`PortfolioValuationEngine` consume it unchanged. Tested end-to-end:
equity, option, future, bond and a mixed portfolio all value off an M19-built snapshot and produce
governed, reproducible `ValuationResult`s.

## 22. Research compatibility

A live snapshot and a historical snapshot use the same canonical interface, so derivative/option/
rates/FX/cross-sectional backtests reconstruct market data PIT-safely. `HistoricalSource` and the
bitemporal `RevisionStore`/`FixingStore` answer "what did we know on date D?" without look-ahead;
`current` is available for reporting. Determinism means a research result is reproducible from its
inputs + conventions + date.

## 23. Production adapter status (`adapters.py`)

`VendorAdapter` subclasses — `BloombergAdapter`, `RefinitivAdapter`, `ExchangeFeedAdapter`,
`BrokerFeedAdapter` — define the exact external→canonical **translation contract**: each ships a
tested `FIELD_MAP` and a pure `to_canonical` (fully implemented and unit-tested). `fetch` raises
`NotImplementedError` with the specific unblock, because the platform is offline by mandate — no
credentials, no network, no false live-functionality claim.

## 24. Tests, benchmarks, scaling

- **Tests:** `tests/research/test_market_data.py` — **206 deterministic, offline tests**. Cover
  the canonical model, identifiers (PIT + no-collapse), calendars, revisions/fixings, sources,
  normalization, quality, diagnostics, rate instruments, curve bootstrap, OIS/multi-curve, credit,
  SABR, SVI, vol-surface calibration + arbitrage, PIT snapshot builder, validators, serialization
  round-trips, registry, adapter contracts, engine façade, M16/M17/M18 integration, determinism and
  edge cases.
- **Financial invariants verified:** calibration instruments reprice to quotes (curves < 1e-12,
  credit < 1e-7); DF > 0 and monotone; forward-rate consistency; survival monotone; hazards ≥ 0;
  SABR recovers truth < 1e-6; SVI residual < 1e-3 with no butterfly; FX reciprocal; identical
  inputs → identical fingerprints; M19 snapshot → M18 valuation reproducible; revision
  reconstruction correct.
- **Full suite:** **1707 passed, 3 skipped** (pre-existing) — zero M1–M18 regressions.
- **Benchmarks** (`scripts/benchmark_m19_market_data.py`, deterministic/offline; machine-dependent):

  | observations | normalize | throughput | quality | snapshot build | peak (build) |
  |--------------|-----------|-----------:|---------|----------------|-------------:|
  | 10,000       | ~0.30 s   | ~33k/s     | ~0.13 s | ~0.44 s        | ~4.6 MB |
  | 100,000      | ~3.6 s    | ~28k/s     | ~0.13 s | ~3.8 s         | ~46 MB  |
  | 1,000,000    | ~37 s     | ~27k/s     | ~0.15 s | ~36 s          | ~467 MB |

  Curve bootstrap (9 instruments) ~20 ms; SVI surface (5 expiries × 5 strikes) ~370 ms; surface
  interpolation (41 strikes) ~0.4 ms; credit bootstrap (4 CDS) ~19 ms.

- **Scaling analysis:** the dominant cost is per-record normalization (pure-Python transform +
  revision dedup); it is linear in record count and single-pass. Snapshot fingerprinting is
  memoized (M18), so snapshot assembly stays linear. Memory grows with the number of *distinct*
  observations retained (dedup collapses revisions). 10M observations in a single process is
  memory-bound; the architecture batches naturally by security or by date (each `HistoricalSource`
  day is independent), and curves/surfaces/snapshots are immutable and cacheable by fingerprint.

## Backward compatibility

Purely additive: a new package + a new test file + a benchmark + this doc, plus index/roadmap
updates. **No M1–M18 source modified.** Full suite 1707 passed, 3 pre-existing skips, zero
regressions.

## Known limitations / Skipped

Each is a bounded interface with a stated unblock — no silent omission.

- **Live market-data feeds** (Bloomberg/Refinitiv/exchange/broker). Adapters ship the translation
  contract only; no live `fetch`. Reason: offline/no-credentials mandate. **Unblock:** implement
  `fetch` against the real endpoint (auth + request) returning raw records; the tested
  `to_canonical` already maps them to PIT-tagged canonical observations.
- **SABR/SVI global joint fit.** Each expiry's smile is calibrated independently and deterministic;
  a joint multi-expiry arbitrage-free surface fit is not. Reason: scope. **Unblock:** a joint
  optimizer behind the existing calibrator seam, using the same residual/arbitrage diagnostics.
- **Credit / CDS.** Deterministic par-CDS hazard bootstrap on a discrete grid — not a full ISDA CDS
  pricer (no accrual-on-default, upfront/points-running conversion, or ISDA calendar). Reason:
  scope. **Unblock:** an ISDA-standard premium/protection-leg pricer behind `CreditCurve`.
- **Business-day calendars.** Weekend mask + sample injected US/UK/India holiday sets 2024-2026 —
  not exhaustive exchange holiday history. Reason: calendar data not in scope. **Unblock:** inject
  full vendor holiday calendars (the `HolidayCalendar`/`JointCalendar` interface is unchanged).
- **Curve interpolation.** Linear-in-zero / log-linear-in-DF (inherited from M18); no splines.
  Reason: M18 convention. **Unblock:** add a spline interpolation policy to M18's `interpolation`.
- **Futures convexity.** Rate futures are bootstrapped as forward-rate agreements on their accrual
  period; no convexity adjustment. Reason: convexity needs a vol input/model. **Unblock:** inject a
  convexity adjustment (Ho-Lee/HW) before bootstrapping the futures node.

## Recommendation for M20 — Live Market-Data & Curve-Construction Layer

Implement the M19 production adapter contracts against a real feed (behind the same
`ProductionMarketDataAdapter`/`VendorAdapter` interfaces, returning immutable PIT-tagged snapshots),
add a joint arbitrage-free surface fit and futures convexity, wire full vendor holiday calendars,
and layer regulatory/client reporting — all slotting into the existing injected seams without
touching the valuation engine.

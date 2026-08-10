# AIDP M16 — Multi-Currency & FX Portfolio Book

## What this is

M16 removes the single-currency assumption from the post-trade stack while preserving
all certified M1–M15 behaviour. It adds a multi-currency portfolio, cash, settlement and
FX-accounting layer: trading / settlement / base currencies, explicit FX conversion, FX
exposure, FX P&L, multi-currency cash and settlement, and cross-currency corporate
actions.

It is **not** an FX strategy, an alpha model, a new execution engine, a new portfolio
accounting engine, or a broker integration. It is an **extension** of the existing
accounting and post-trade infrastructure.

### Package

`src/aurelius/research/fx/` — import as `from aurelius.research import fx`.

## Architecture

The central decision: **do not fork M11 accounting and do not build a second portfolio
accounting system.** A `MultiCurrencyBook` holds **one reused M15 `PostTradeEngine` per
currency** — each is a self-contained single-currency post-trade book (its own M11
`PortfolioState`, settlement-aware cash ledger, settlement engine, event log) denominated
in that currency. On top, M16 adds only the **FX overlay**:

- explicit, auditable `FXConversion`s that move cash between currency books,
- a running FX cash position for **realized FX P&L**,
- **base-currency valuation** that translates each book at an explicit as-of rate.

```
book_fill(currency=EUR, funding_currency=USD)
  → convert USD→EUR (explicit FXConversion; USD book cash down, EUR book cash up)
  → EUR PostTradeEngine.book_fill   (pure M15 → pure M11 accounting)
valuation(as_of) = Σ_ccy book_value_local(ccy) × fx_rate(ccy→base, as_of)
```

Backward compatibility is **structural, not bolted on**: a book whose only currency is
the base, with a unit rate, delegates every call to exactly one `PostTradeEngine` — i.e.
it *is* M15. No M11–M15 source was modified.

## Currency model (`currency.py`, `models.py`)

Every monetary quantity is currency-tagged. ISO-4217-style codes are validated and
normalized at the trust boundary (`validate_code`, `require_same` → `CurrencyMismatchError`
on mismatch). `CurrencyRole` names base / trading / settlement / cash / reporting roles.
`Currency`, `CurrencyPair` (base/quote), `FXRate`, `FXRateSnapshot` are frozen models.

## FX rate architecture (`rates.py`)

`FXRateProvider` is a dependency-injected ABC. A provider knows a *canonical* rate for
the pairs it covers; everything else derives deterministically — the **inverse by
reciprocal** (so `rate(A,B)·rate(B,A) == 1` to machine tolerance) and **cross rates via a
pivot** currency. Convention: `rate(base, quote)` = units of `quote` per unit `base`.

Implementations: `StaticFXRateProvider` (constant), `HistoricalFXRateProvider` (as-of
lookup with optional `max_staleness_days` → `StaleFXRateError`), `DeterministicMockFXProvider`
(pure-function rates for tests/benchmarks, no randomness/network), and
`ProductionFXRateAdapter` (interface-only DI seam for a live feed). Zero/negative/NaN
rates raise `InvalidFXRateError`; unknown pairs raise `MissingFXRateError`. Every
conversion is an explicit `FXConversion` recording source/target/amounts/rate/direction
(direct/inverse/cross/identity)/as-of/provider — no implicit conversion anywhere.

## Multi-currency accounting (`accounting.py`, `book.py`, `multi_currency_cash.py`)

Currencies are never collapsed internally — each per-currency book keeps its own M15
settlement-aware `CashLedger` and M11 `PortfolioState`. The currency-aware adapter reads
M11's local quantity / cost basis / realized / unrealized P&L and translates to base at an
explicit as-of rate (`position_accounting`, `base_realized_pnl`, `base_unrealized_pnl`).
**Realized FX P&L** on conversions is tracked with a weighted-average base-rate position
per currency: acquiring a currency via FX records its base cost; converting out realizes
`(current_base_rate − avg_base_rate) × units`.

## FX exposure and P&L (`exposure.py`, `pnl.py`)

`fx_exposure` reports currency-by-currency exposure in base terms, split into cash /
security / settlement components and netted against abstract hedges, with gross / net /
long / short and concentration (largest-currency share). The base currency carries no FX
exposure.

`fx_pnl` decomposes the base-currency change of each currency bucket over a marking
period into **local / FX (translation) / interaction** via the exact identity
`Δ(V·R) = R0·ΔV + V0·ΔR + ΔV·ΔR`, which sums to the true base change by construction — the
decomposition **always reconciles**. Realized FX (from conversions) is carried at the
report level.

## Settlement integration (`settlement_fx.py`)

Each per-currency book settles its own obligations in its own currency on the reused M15
T+N business-day calendar. `settlement_by_currency` and `obligations_by_currency`
aggregate by currency; `fund_settlement` converts exactly a pending outflow out of a
funding currency before settlement (cross-currency funding). If the FX rate is
unavailable the conversion raises — **failed FX funding** the caller turns into a failed
settlement.

## Corporate actions (`corporate_actions.py`)

A thin wrapper over M15 corporate actions: an action on a security is applied inside that
security's trading-currency book, so dividend / cash-merger / delisting cash lands in the
correct currency automatically (M15/M11 accounting reused verbatim). An optional
`receive_currency` converts the proceeds, preserving source currency, received currency,
and the FX conversion used.

## Risk integration & stress (`risk.py`)

Reuses M13's idea (z·σ·exposure) without duplicating its covariance engine — per-currency
vols are **injected**. `fx_risk_report` exposes FX volatility contribution, currency
concentration, and a **diagonal FX VaR** (full cross-currency covariance is a documented
interface). `FXLimits` + `check_fx_limits` warn/reject on excessive per-currency or gross
FX exposure. Deterministic currency stress: `CURRENCY_SCENARIOS` (USD ±10, EUR ±10, INR
depreciation, JPY appreciation, broad USD, EM shock) plus custom **simultaneous
multi-currency** shocks; a base-currency shock translates into a matching decline of every
foreign currency.

## FX hedging interface (`hedging.py`)

NOT an FX trading strategy. `FXHedge` represents a hedge abstractly as a base-currency
notional offsetting a currency's exposure; `make_forward/future/swap` record the
instrument and optional rate/maturity. `fx_exposure` nets hedges out (`unhedged_by_currency`).
Hedges are represented, not priced or settled — see Limitations.

## Reconciliation (`reconciliation.py`)

Reuses each per-currency book's M15 reconcile (cash vs M11, positions vs broker), tagged
with its currency, then adds FX faces: conversion conservation (`to == from·rate`),
non-positive / wrong FX rate, and base-value consistency. Only diffs — never re-accounts.

## Performance attribution (`performance.py`)

`currency_attribution` extends M15 performance to the currency dimension, decomposing the
base return into local / FX / interaction via the `fx_pnl` identity — always reconciles.

## Reporting (`reporting.py`)

`MultiCurrencyPortfolioReport`, `CashByCurrencyReport`, `FXExposureReport`, `FXPnLReport`,
`FXReconciliationReport`, `SettlementCurrencyReport`, `FXRiskReport`,
`CurrencyAttributionReport`.

## Tax interface

The M15 FIFO tax-lot framework is preserved and continues to operate **per currency**
(each book has its own trade stream to replay). A currency-aware base-value/jurisdiction
overlay is a documented extension — see Limitations. No jurisdiction-specific rates (M15's
stance, unchanged).

## Serialization & registry (`serialization.py`, `registry.py`)

Deterministic JSON: base currency, per-currency book summaries, the full FX conversion
audit, hedges, realized FX P&L, base valuation/cash, diagnostics and fingerprint. Sorted
keys, currency-complete — every conversion round-trips exactly (`conversion_from_dict`).
`attach_fx` mirrors M15's registry attachment: base-currency metrics + a hash-recorded
session artifact + session fingerprint, extending the research→…→post-trade→FX lineage.

## Validation & determinism (`validation.py`, `diagnostics.py`)

`validate_book` runs each per-currency book's M15 invariants, then the FX faces:
conversion conservation, non-positive rate rejection, and rate-inversion consistency for
every traded currency. `fingerprint` combines each book's M15 fingerprint with the FX
overlay (conversions, realized FX, base value) — two identical runs match.

## Tests

`tests/research/test_fx.py` — **140 deterministic tests**. Coverage: currency model &
validation, FX conventions (direct/inverse/cross, inversion invariant), all four
providers (incl. zero/negative/missing/stale rejection), conversions (round-trip,
multi-hop, dict round-trip), cross-currency trades (all six spec cases), multi-currency
cash / valuation / exposure / P&L (reconciliation), realized FX P&L, settlement &
cross-currency funding (incl. failed FX funding), corporate actions, currency-aware
accounting, reconciliation (bad conversion/rate/broker), risk & limits & VaR & stress
(single + simultaneous), hedging, performance attribution, reporting, serialization
round-trip, registry, validation, **backward compatibility with M15** (single-currency
book matches M15 cash/value/fingerprint), determinism, invariants, and edge cases.

Full research-track suite: **595 passed, 1 skipped — zero regressions** (455 pre-M16 +
140 M16).

## Benchmarks

`scripts/benchmark_m16_fx.py` — offline, single core, `DeterministicMockFXProvider`.

| currencies | positions | events | book s | val s | conv ms | recon s | pnl s | ser s | peak MB |
|-----------:|----------:|-------:|-------:|------:|--------:|--------:|------:|------:|--------:|
| 100 | 1,000 | 3,000 | 0.08 | 0.005 | 0.03 | 0.004 | 0.001 | 0.04 | 2.4 |
| 1,000 | 10,000 | 30,000 | 0.90 | 0.10 | 0.05 | 0.067 | 0.012 | 0.45 | 23.5 |
| 50 | 10,000 | 30,000 | 1.01 | 0.06 | 0.05 | 0.008 | 0.001 | 0.07 | 18.9 |
| 100 | 100,000 | 300,000 | 10.2 | 0.71 | 0.05 | 0.107 | 0.001 | — | 194.5 |
| 200 | 350,000 | 1,050,000 | 37.0 | 2.94 | 0.06 | 0.372 | 0.002 | — | 693.0 |

Valuation and reconciliation scale **linearly** (reconcile 0.37 s over 1.05M events); a
single FX conversion is **sub-millisecond** regardless of book size; P&L attribution is
snapshot-based (O(currencies), ~2 ms). Booking dominates wall time (it is full M11
accounting per fill, ~10k fills/s); it scales with positions/currencies with no dense N×N
structures. FX rate lookups are O(1) with pivot cross.

## Backward compatibility

Verified in-suite: a single-currency `MultiCurrencyBook` (base = only currency, unit rate)
booking the same fills as a raw M15 `PostTradeEngine` produces **identical** cash, total
value, and M15 fingerprint (`test_single_currency_matches_m15_*`). No M11–M15 source file
was modified; all 455 pre-M16 research-track tests pass unchanged. Single-currency cash,
settlement, corporate actions and P&L therefore produce the same results as before M16. No
intentional numerical differences were introduced.

## Known limitations / Skipped

Nothing requested in the M16 prompt was skipped. Deliberate, documented ceilings, each
with a concrete unblock and a dependency-injected extension point where relevant:

1. **FX hedges are represented, not priced or settled.** `FXHedge` (forward/future/swap)
   carries a base-currency notional that nets exposure, per the prompt's "interface for
   future" instruction. *Reason:* full hedge pricing/settlement was explicitly out of
   scope ("Do NOT build a full FX trading strategy"). *Unblock:* a hedge pricing/settlement
   engine turning `FXHedge`s into dated cash flows and mark-to-market P&L.
2. **Full cross-currency FX VaR is a diagonal (independent-currency) approximation.**
   `fx_risk_report.fx_var` sums `(exposure·vol)²`; it does not consume a currency
   correlation matrix. *Reason:* a full FX covariance source is not wired in offline (M13
   covariance is equity-oriented). *Unblock:* inject a currency correlation/covariance
   matrix and replace the diagonal sum with `√(wᵀΣw)`.
3. **Production FX feed is interface-only** (`ProductionFXRateAdapter`). *Reason:* the
   platform is offline — no live rate connection. *Unblock:* implement `_canonical`
   against a real feed (ECB/Bloomberg/Reuters).
4. **Realized FX P&L is scoped to explicit conversions.** Trade-driven cash translation
   (e.g. FX movement on foreign sale proceeds) shows up as unrealized translation P&L via
   valuation snapshots, not as realized FX on the trade. *Reason:* attaching a base cost
   basis to *every* cash flow (not just FX transactions) is heavier and less standard than
   the "FX trading result" convention used here. *Unblock:* extend the FX cash-basis
   tracker to every cash flow, not only conversions.
5. **Tax base-valuation overlay is not currency-translated.** M15's FIFO tax lots run per
   currency (correctly, in local currency); a base-currency tax valuation with the FX rate
   used for tax is not computed. *Reason:* jurisdiction-specific tax FX conventions
   (transaction-date vs year-end rate) are country rules, out of scope like M15's tax
   rates. *Unblock:* a `JurisdictionRule` extension that specifies the tax FX convention
   and translates lots to base.
6. **Corporate-action cost-basis** inherits M15's simplifications (merger basis scales with
   ratio; cash-in-lieu / spin-off allocation not modelled) — now also in the security's
   trading currency. *Unblock:* per-action, per-jurisdiction basis-allocation rules.

## Future extensions

Multi-currency derivatives and cross-currency swaps, a live rate feed + hedge
pricing/settlement engine, a full FX covariance/VaR model, currency-translated tax
reporting, and a regulatory/client reporting layer over the FX event stream. The seams
already exist: `FXRateProvider` for feeds, `FXHedge` for hedge infrastructure, the injected
vols for a covariance model, and the per-currency M15 event logs for streaming projections.

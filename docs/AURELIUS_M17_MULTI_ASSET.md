# AIDP M17 — Multi-Asset & Derivatives Accounting Engine

**Commit:** `22b4c38`

## What this is

A general, instrument-agnostic framework for institutional accounting and lifecycle
management of equities, futures, options, forwards, swaps and fixed income — layered
**additively** on top of M11–M16. It is **not** a trading-strategy engine, a pricing
research platform, an alpha model, or a new risk engine. It reuses M11 accounting, M12
portfolio state, M13 risk, M14 execution, M15 settlement and M16 FX, and does **not**
duplicate positions, cash accounting, settlement, risk math or FX conversion.

The design guarantee: **equity portfolios behave identically after M17.** An equity trade
delegates straight through to the reused M15 `PostTradeEngine`, so its cash, positions,
P&L and event fingerprint are byte-identical to pre-M17.

### Package

`src/aurelius/research/instruments/` — 24 modules (see below).

## Architecture

```
InstrumentBook  (lifecycle.py) ── the orchestrator
  ├── PostTradeEngine        (reused M15)  ← single cash / equity book of record (M11 ledger)
  ├── InstrumentRegistry     (registry.py) ← id → Instrument, the source of instrument truth
  ├── {DerivativePosition}   (positions.py)← derivative overlay (futures/options/forwards/…)
  ├── margin_posted / collateral            ← margin & collateral accounts
  └── EventLog               (reused M15)  ← append-only InstrumentEvent spine (replayable)
```

There is exactly **one** cash ledger — M11's, via the engine. Every derivative cash flow
(premium, initial margin, variation margin, settlement) is posted through
`engine.post_cash`, so M11/M15/M16 accounting stays the single source of truth. Derivatives
that M11 was never built for (contract multipliers, margin, premium) get an in-memory
`DerivativePosition` overlay; **cash never forks.**

## Instrument model (`models.py`, `instrument.py`)

One unified frozen `Instrument`: `instrument_id`, `type`, `currency`, `exchange`,
`contract_size`, `expiry`, `calendar`, `metadata`, plus derivative extras (underlying,
strike, right, margin rates, settlement style). Types: `EQUITY`, `FUTURE`, `OPTION`,
`FORWARD`, `SWAP`, `BOND`.

The one place a fill becomes cash is `instrument.trade_cash`, keyed on a **cash convention**
so no asset class re-derives it:

| Convention  | Cash at trade                              | Used by                     |
|-------------|--------------------------------------------|-----------------------------|
| `PRINCIPAL` | `-(qty · price · contract_size) - cost`    | equity, option premium, bond principal |
| `MARGINED`  | `-cost` (notional not exchanged)           | future, forward             |
| `NPV`       | `-cost` (valued/settled by a provider)     | swap                        |

## Position model (`positions.py`)

`InstrumentPosition` (immutable snapshot) and `DerivativePosition` (mutable overlay) carry
quantity, notional, market value, cost basis, realized/unrealized P&L, currency, margin and
collateral requirements, and contract metadata. Average-cost, sign-aware realization —
identical convention to M11's equity accounting — so a crossing trade realizes the closed
portion and re-bases the remainder. **Adapters around existing position objects; no second
accounting system.**

## Equity backward compatibility

Equities are the degenerate case (`contract_size` 1, `PRINCIPAL`, no expiry). `book_trade`
routes them straight to `PostTradeEngine.book_fill` — the position lives in the M11
`PortfolioState`, not the overlay. Verified: `test_equity_delegates_to_m15_identically`
asserts an equity-only `InstrumentBook` matches a bare `PostTradeEngine` on cash **and**
post-trade fingerprint. All 1330 M1–M16 tests still pass unchanged.

## Futures (`futures.py`)

Long/short, contract multiplier, initial & maintenance margin, **true daily settlement**:
`mark()` posts variation margin as cash, folds the day's P&L into realized, and re-bases the
contract to the settlement mark, so unrealized stays 0 (no double-count — the P&L is in cash
once, not also in unrealized). Expiry via `expiry.py` (cash or physical). `futures.roll`
returns the close-front / open-back fill pair.

## Options (`options.py`, `exercise.py`, `expiry.py`)

European calls/puts, long/short. Premium is `PRINCIPAL`, so a long pays / a short receives at
trade with no special accounting. Tracks premium, strike, expiry, underlying, exercise and
assignment status, settlement type. At expiry: ITM long → exercise, ITM short → assignment
(cash-settle intrinsic by closing at intrinsic, or physical-deliver the underlying via a
hand-off fill); OTM → expire worthless (position closed at 0, premium loss realized).

Pricing is **dependency-injected** (`pricing.py`): `PricingProvider` interface, a closed-form
`BlackScholesPricer` (verified against put-call parity), a `DeterministicMockPricer` for
offline tests/benchmarks, and a documented Monte-Carlo extension point.

## Option Greeks interface

`GreeksProvider` (injected) exposes delta, gamma, theta, vega, rho; `BlackScholesPricer`
implements it. The risk layer consumes Greeks — it does **not** rebuild M13.

## Forwards, swaps, fixed income

- **Forwards** (`forwards.py`): currency & commodity, no cash at inception, MTM to the
  forward mark, settle the difference; `fx_forward` carries the pair and values through M16.
- **Swaps** (`swaps.py`): IRS / currency / equity swaps as legs + payment schedule + cash
  flows. Valuation is an injected `ValuationProvider` — M17 captures the contract, not the
  pricing.
- **Fixed income** (`fixed_income.py`): bonds quoted per 100 face (`contract_size = face/100`,
  so principal falls out of `trade_cash`), deterministic coupon schedule / cash-flow
  generation, YTM and duration delegated to an injected `YieldProvider`.

## Margin engine (`margin.py`)

Initial + maintenance from instrument rates × notional, margin calls when posted margin
falls under maintenance, and a `liquidation_warning` hook. Margin is exposed to M13 as an
exposure (see risk integration).

## Collateral (`collateral.py`)

Cash and security collateral, per-asset haircuts, currency-tagged. Post-haircut `value`
feeds the margin check; a non-base collateral balance converts through the injected M16 FX
provider (`base_value`).

## Valuation (`valuation.py`)

Every valuation requires **instrument + date + market inputs + currency + provider** —
nothing hard-coded. `PricingProvider` / `MarkProvider` supply the per-unit mark; the module
turns it into market value and unrealized P&L, optionally converting to a base currency via
an M16 FX provider.

## Risk integration (`risk.py`)

Feeds sensitivities **into** M13 — notional, delta ($), gamma, vega, theta, rho, duration,
margin, leverage — via `to_m13_inputs`. Greeks come from the injected provider; an
equity-only book reports pure notional/delta with everything else zero (identical risk to
pre-M17). **Does not duplicate VaR.**

## Settlement integration (`settlement.py`)

Bridges M15 settlement and the M17 expiry/exercise flows. Equity/bond fills settle through
`PostTradeEngine.settle`; derivative expiry/exercise settle via `expiry`. Cash vs physical
is the instrument's `settlement_style`; physical hands off an underlying fill for M14
execution to apply.

## Reconciliation (`reconciliation.py`)

Internal book vs broker / clearing / settlement / margin / collateral. Detects
`missing_contract`, `wrong_quantity`, `wrong_valuation`, `wrong_margin`, `missing_exercise`,
`settlement_mismatch`. Deterministic, tolerance-based, typed breaks.

## Serialization, validation, diagnostics

`serialization.py` → deterministic JSON (sorted keys, rounded money, full event log); two
identical books serialize byte-identically. `validation.py` → cheap invariant checks.
`diagnostics.py` → health summary + order-independent `blake2b` fingerprint over settled
facts, so replaying the same events reproduces it exactly.

## Lifecycle events

`InstrumentEvent` (append-only, reusing the M15 `EventLog`) covers creation, trade,
settlement, mark-to-market, margin call, expiry, exercise, assignment, roll, corporate
action, termination.

## Tests

`tests/research/test_instruments.py` — **123 deterministic, offline tests**. Cover instrument
model + registry, equity backward compatibility (byte-identical to M15), futures accounting /
margin / daily settlement / roll, option lifecycle (premium, exercise, assignment, expiry,
ITM/OTM, physical), forwards, swaps, fixed income, pricing/greeks/yield providers, margin &
collateral, risk integration, settlement, reconciliation, serialization/determinism,
validation, diagnostics, failure scenarios and edge cases.

Full suite: **1330 passed, 3 skipped** (pre-existing) — all M1–M16 green.

## Benchmarks

`scripts/benchmark_m17_instruments.py` (deterministic, offline). Representative run:

| instruments | positions | events   | book   | mark    | risk    | margin  | recon   | serialize | peak    |
|-------------|-----------|----------|--------|---------|---------|---------|---------|-----------|---------|
| 1,000       | 750       | 2,750    | 0.05s  | 0.014s  | 0.006s  | 0.001s  | 0.005s  | 0.32s     | 12 MB   |
| 10,000      | 7,500     | 27,500   | 0.55s  | 0.19s   | 0.07s   | 0.007s  | 0.06s   | 3.2s      | 119 MB  |
| 25,000      | 18,750    | 68,750   | 1.65s  | 0.54s   | 0.18s   | 0.02s   | 0.19s   | 8.2s      | 299 MB  |

**1M lifecycle events**: 25k instruments × 55 mark rounds → 1,081,250 events in 4.4s
(~0.25M events/s). Numbers are machine-dependent; the point is linear scaling.

## Backward compatibility

Mandatory and met:

- All M1–M16 tests pass (1330 passed, 3 pre-existing skips).
- Equity portfolios produce identical cash, positions, P&L and post-trade fingerprint
  (`test_equity_delegates_to_m15_identically`).
- The only change to existing code is **two additive enum members** on M15's `CashType`
  (`MARGIN`, `PREMIUM`) for derivative cash flows — no existing member changed, no existing
  test enumerates the set, so no numerical difference to any equity flow.

## Known limitations / Skipped

Every item below is a deliberate **interface with an injected provider**, matching the
milestone's "do not implement full pricing" instruction — not a silent omission.

- **Full option pricing / Monte-Carlo.** Skipped: only the `PricingProvider` interface, a
  closed-form Black-Scholes reference, and a deterministic mock ship. Reason: M17 is an
  accounting/lifecycle engine, not a pricing platform (explicit milestone scope). Unblock:
  implement `PricingProvider.price` with a Monte-Carlo/vol-surface pricer (the documented
  extension point in `pricing.py`).
- **Swap pricing / curve building.** Skipped: swaps carry legs + schedule + cash-flow
  interface; NPV is an injected `ValuationProvider`. Reason: same scope boundary. Unblock:
  a discount-curve provider implementing `cash_flows`/NPV.
- **Bond analytics (YTM/duration/convexity).** Skipped: `YieldProvider` interface + a flat
  mock. Reason: same. Unblock: a real yield/duration provider.
- **American exercise.** Only European exercise is modelled (`ExerciseStyle.EUROPEAN`).
  Reason: milestone specifies European options. Unblock: an early-exercise policy on
  `exercise.py`.
- **Physical settlement delivery.** `exercise`/`settlement` produce an underlying **fill
  hand-off dict** but do not auto-book it into M14. Reason: keeps M17 additive and lets the
  caller/execution own delivery. Unblock: wire the hand-off into an M14 order.
- **American/exotic margin (SPAN, portfolio margin).** Margin is flat rate × notional.
  Reason: institutional margin models are broker-specific. Unblock: a `MarginModel`
  provider (the rates are already injectable per instrument).

## Future extensions

Monte-Carlo & vol-surface pricers, discount-curve swap valuation, real bond analytics,
American exercise, SPAN/portfolio margin, automated physical-delivery booking into M14, and
cross-currency-swap valuation through M16.

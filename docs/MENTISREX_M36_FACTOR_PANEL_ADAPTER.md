# M36 — ResearchMatrix → Factor-Panel Adapter

**Certification report.** P2. Connects the M34/M35 factor engine to real PIT
universe data. Additive; frozen `ew-momentum-exp v1.0.0`
(`b69961b65bab226a500d71f45709945b`) untouched.

## Objective
Turn a time series of PIT `ResearchMatrix` snapshots into the per-date dict panels
the campaign consumes: a signal cross-section per rebalance + a PIT-correct
forward-return label to the next rebalance.

## Implementation
`research/factor_panel.py`, `panels_from_matrices(matrices, feature, close_fn, symbol_fn, apply_direction=True)`:
- Signal cross-section from `matrix.frame[feature]`, NaNs dropped; a `directions`
  == "lower" feature is negated so larger oriented value = stronger long.
- Forward return is rebalance-to-rebalance, both legs back-adjusted into the
  **endpoint** frame (`knowledge_date = t_{i+1}`) so an in-window split can't
  distort the ratio. Signal at t_i uses only the t_i matrix — no look-ahead. Names
  missing a price on either leg (delisted before t_{i+1}) are dropped from that
  label.
- Duck-typed: `close_fn = PitPriceStore.close_as_of`,
  `symbol_fn = SecurityMaster.historical_identifier` in production; fakes in tests.

## Tests — `tests/research/test_factor_panel.py` (5, all pass)
Aligned panels + last date dropped; forward return math; "lower" direction
negated; missing forward price (delisting) dropped; needs ≥2 matrices;
**end-to-end into `FactorCampaign` → PROMISING** on a signal-driven price book.

## Regression
`pytest tests/research tests/validation` → **2209 passed, 2 skipped, 0 failures.**

## Known limitations / Skipped
- **Mid-hold ticker change**: `symbol_fn` is resolved at entry `t_i`; if a ticker
  changes inside the holding window the endpoint close is still looked up under the
  entry symbol. Rare; a proper fix resolves the symbol per leg. Recorded per
  CLAUDE.md; unblock = resolve `symbol_fn(sid, t_next)` for the exit leg.
- **Delisting return not booked**: delisted names drop from the label rather than
  booking a terminal (often negative) return — conservative for IC, but a
  liquidation-return model belongs in the backtest layer, not the factor IC panel.
- Runner/service DoF-ledger adoption still deferred (M33).

## Next milestone
M37: live factor sweep — run `panels_from_matrices` over the real universe across
the M32 feature families through `FactorCampaign`, producing the first
DoF-corrected, redundancy-screened factor library from live data.

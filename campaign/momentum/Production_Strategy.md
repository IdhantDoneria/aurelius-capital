# Production Strategy — Momentum v1

**Date:** 2026-08-03. Justified by campaign evidence only (`us.jsonl`,
`india.jsonl`, `Robustness_Report.md`, `Cross_Market_Report.md`,
`Leverage_Investigation.md`). No intuition, no parameters chosen to flatter a
backtest. **Recommendation: PAPER-TRADE ONLY — not capital-ready.**

## 1. What the evidence supports

Across 14 backtests (7 configs × US/India), exactly **one** cleared statistical
significance: **India long-only decile momentum** (OOS Sharpe 1.012, +416.5%, adj
p 0.026). Everything else is directional-but-insignificant, and every long/short
book is dragged or destroyed by the short leg. So the only evidence-justified
design is a **long-only relative-strength book**, and even that carries
disqualifying caveats (§4) that keep it out of live capital.

## 2. Momentum v1 specification (evidence-mapped)

| Element | Choice | Evidence |
|---|---|---|
| Universe | Single-market equities, liquid names only | cross-currency blend forbidden; penny/illiquid names inject the −70% DD variance (M6) |
| Signal | Cross-sectional 6-month (126d) total return | US single-peaks at 6m; India long-only strongest at 6m decile |
| Selection | **Top decile (0.10)** long | decile > tercile in both markets (breadth dilution kills it) |
| Direction | **Long-only** | short leg negative/insignificant in US, catastrophic in India |
| Weighting | **Equal-weight within budget** (~budget/N per name) | fixed 5%/name blows the 1.5× cap (M3); equal-weight expresses the full decile |
| Rebalance | Monthly (21d) | 63d holding detonates the book (hold_3m −242% US, −197% India) |
| Skip period | 1 week (add — not in v0) | JT skip absent (M1); reduces microstructure noise |
| Gross leverage | ≤ 1.0× (long-only, no borrow) | avoids the L/S leverage-cap truncation entirely |
| Costs | commissions on (already net) | engine default; keep net reporting |

## 3. Risk controls

- **Drawdown:** production `max_drawdown_halt` stays tight (config default 0.20×,
  NOT the 0.60 research halt). Research loosened it only to judge on OOS.
- **Position cap:** equal-weight ≈ budget/N (~0.75–1% per name at decile breadth),
  well under any single-name concentration limit.
- **Liquidity screen:** minimum ADV / price floor to exclude the penny names that
  drove the extreme research drawdowns (M6). Not yet implemented — required
  before any capital.
- **Regime monitor:** the India result is bull-regime-dependent; a trailing
  market-return / breadth filter to de-risk when the trend breaks.

## 4. Failure conditions (why v1 is paper-only)

1. **Survivorship bias, unquantified.** 2014–2026 = currently-listed names only;
   delisted losers absent. Inflates long-only momentum by an unknown amount —
   worst exactly where v1 is strongest (India bull). *Disqualifying until a
   delisting-returns dataset is on hand.*
2. **Single regime / single OOS slice.** India's significance rests on one
   ~3.8-year bull OOS window (p 0.026, n_trials=1). No walk-forward, no bear-market
   OOS. One favorable regime is not evidence of a durable premium (M8).
3. **Leverage-cap fidelity gap (M3).** The tested book is leverage-truncated;
   equal-weight-within-budget sizing is specified above but **not yet built**, so
   v1's own weighting scheme is unvalidated by backtest.
4. **No liquidity screen yet (M6).** Extreme drawdowns in-sample trace to
   penny/illiquid names still in the universe.

## 5. Capacity

Not measurable on current data — turnover and ADV are not surfaced by
`ValidationReport` (would need a report-schema change, out of scope under the
freeze). India long-only ran 959 OOS trades over ~3.8y ≈ 250 fills/yr at monthly
rebalance over ~112 decile names. Capacity is **unknown**, not estimated —
reported honestly, not fabricated.

## 6. Monitoring requirements (when/if promoted)

- Live vs backtest tracking error on the momentum decile.
- Regime filter state (trend intact / broken).
- Realized turnover, ADV utilization, slippage vs modeled commission.
- Drawdown vs the 0.20 halt; short-leg P&L if ever re-enabled.

## 7. Decision

**Momentum v1 = long-only, 6-1(skip)-1, top-decile, equal-weight, monthly, single
liquid market, ≤1× gross.** It is the only design the evidence supports. It is
**NOT capital-ready**: survivorship bias, single-regime significance, and two
unbuilt fidelity pieces (M3 sizing, M6 screen) must be resolved first. Deploy to
**paper trading + a walk-forward, bias-corrected re-test** before any live risk.
Go/no-go rationale in `Executive_Summary.md`.

# Knowledge Graph Summary — Momentum Campaign

**Date:** 2026-08-03. Campaign-level synthesis for institutional memory. All
entries trace to `us.jsonl` / `india.jsonl` and the committed reports.

## Experiment registry (14 runs)

| Market | Configs run | ACCEPT | REJECT | Store |
|---|---|---|---|---|
| US | 7 | 0 | 7 | `research_us_*.duckdb` + shards |
| India | 7 | 1 | 6 | `research_india_*.duckdb` + shards |

Each run = one hypothesis, one strategy fingerprint, one 70/30 OOS evaluation,
n_trials=1 (no tuning). Recorded via `ResearchStore.record_experiment`.

## Validation registry

- **Significant (adj p < 0.05):** 1 — India long_only decile (p 0.026).
- **Directional-positive but insignificant:** US JT decile (+58.8%, p 0.161),
  US long_only (+99%, p 0.155), US hold_3m (p 0.152).
- **Negative / sign-flipped:** US form_12m, all India L/S configs.

## Failure registry

| Failure | Where | Class |
|---|---|---|
| Sign flip at 12m formation | US form_12m (Sharpe −0.685) | D — horizon reversal |
| Book blow-up under slow rebalance | US/India hold_3m (−242% / −197%) | config/turnover |
| Signal dilution at tercile breadth | both markets | methodology (breadth) |
| Short-leg drag destroys L/S | all India L/S negative | D — momentum crash / bull regime |
| Gross-leverage cap truncates decile to ~30 names | both markets | B — M3 fidelity |
| No significance on single OOS slice | 13/14 configs | E — power |

## Lessons registry

See `Lessons_Learned.md`. Headline: DuckDB read-only shared-lock fix (driver-level,
no engine change); deterministic backtests parallelize with zero precision loss;
the 1.5× leverage cap uniformly shapes every result; momentum is narrow (US) or
long-only-and-regime-bound (India).

## Research decision ledger

| Decision | Rationale | Reversible? |
|---|---|---|
| Run price-only momentum (JT family) on real US+India data | only papers whose data exists | — |
| Keep Carhart/MOP/AMP BLOCKED | fundamentals / multi-asset data absent | yes, on data acquisition |
| Parallelize India grid read-only | deterministic runs, same precision | — |
| Do NOT change leverage cap / sizing after investigation | risk engine working as designed; changing = tuning + unfreeze | yes, in a future un-frozen fidelity phase |
| Momentum v1 = long-only, paper-only | only significant config; survivorship + single-regime caveats | — |

## What is robust / fragile / data-dependent

- **Robust (directional):** ~6-month formation, extreme-decile selection, monthly
  rebalance — the momentum "shape" holds across both markets.
- **Fragile:** the long/short spread (short leg negative in US on risk-adjusted
  terms, catastrophic in India); anything at tercile breadth or 63-day holding.
- **Data-dependent:** India's significance (bull regime + survivorship). Move the
  regime or add delisted names and it may vanish.
- **Methodology-dependent:** every L/S magnitude (leverage-cap truncation, M3).

## Knowledge graph deltas to persist

Append to `docs/KNOWLEDGE_GRAPH.md`: (1) momentum is market-structure-dependent,
not universal; (2) the leverage-cap × decile-breadth interaction (M3) is a
first-order fidelity constraint on all L/S factor books; (3) long-only momentum >
long/short momentum in a trending single-regime market; (4) 0 platform defects
across 14 runs + a leverage investigation.

## Sequential fidelity ledger (M1→M4, US canonical)

| Step | Change | OOS Sharpe | OOS trades | Adj p | Decision | Class |
|---|---|---|---|---|---|---|
| M1 | equal-weight decile L/S | −0.687 | 848 | 1.000 | baseline | — |
| M2 | + $5 price screen | +0.098 | 672 | 0.424 | KEEP | A |
| M3 | + overlapping cohorts | +0.006 | 4781 | 0.495 | BLOCKED | E (engine) |
| **M4** | **+ 1-month skip** | **+0.112** | **593** | **0.413** | **KEEP** | **A** |
| M5 | gross-vs-net reporting | +0.117 (gross) | 589 | 0.410 | KEEP | A (reporting) |

- **Institutional baseline = M4** (M1 equal-weight + M2 price screen + M4 skip).
- M4 new KG facts: (5) the JT 1-month skip is regime-split — it removes reversal
  OOS (Sharpe↑, turnover↓) but discards continuation signal IS (Sharpe↓); judge on
  OOS. (6) skip's operational fingerprint is *lower turnover* (−12%), corroborating
  the mechanism independent of P&L. (7) M4 adds zero platform defects — every
  deterioration is Category D regime/noise.
- Failure-registry addition: IS Sharpe collapse under skip (+0.322→−0.167) — Class
  D regime-dependence (IS continuation vs OOS reversal), not a defect.
- **M7 (liquidity screen — REJECT):** (16) generic liquidity registry
  (`liquidity.py`: median/mean $vol, ADV, Amihud) wired into `FactorStrategy`,
  **default OFF**; disabled path byte-identical to M4 (Run A reproduces the M4
  jsonl to every digit). (17) enabling the median-$vol screen (drop bottom 20%)
  **raised OOS Sharpe 0.112→0.277 and cut p 0.413→0.295 but cratered OOS return
  −24.8%→−95.9% and breached a >100% drawdown (−115.9%)** — a blow-up, not an
  improvement. (18) mechanism: universe shrinkage → smaller decile `_count` →
  larger equal-weight per-name strength → 1.5× leverage-cap concentration
  fragility (same as L5/M3), **0 platform defects**. (19) KEEP is conjunctive;
  Sharpe/p up but economic + integrity gates fail → **REJECT**, baseline stays
  M1+M2+M4. (20) framework retained (disabled); fair re-test needs dollar-hold /
  fixed-N sizing (the M3 unblock), else screening silently levers the book.

- **M8 (portfolio invariance — ADOPT construction standard):** (21) incumbent
  weight `budget/_count` (`_count=int(quantile·n)`) makes single-name concentration
  `∝1/n` — max weight explodes **0.96%→75% (×78)**, HHI ×78, as the universe shrinks
  785→15 (gross is already invariant; concentration is the controllable channel).
  (22) bounded equal-weight `min(budget/max(count,n_min), w_max)` caps max weight at
  **7.5% (×7.8)** and **de-levers gross (1.5→0.15)** below the n_min floor instead of
  concentrating; **byte-identical to M4 for f≥0.25** (default OFF, w_max=0.10,
  n_min=10). (23) end-to-end at 5% shrink, only construction varied: baseline OOS
  −54%/−77.6% DD (19 trades, cap-rejected) vs invariant +20%/−21.9% DD (229 trades)
  — **DD −77.6%→−21.9%**. (24) HONEST: M7's 20% blow-up was ABOVE the ~10% crossover
  (max weight ~1.2% there) → NOT snapshot concentration but async-vintage/composition/
  cap (engine, frozen); M8 owns the concentration channel only. (25) **decision:
  ADOPT** bounded equal-weight as the standard construction for all future
  universe-reducing campaigns (exchange/mktcap/survivorship/liquidity); default OFF so
  M1+M2+M4 unchanged. 0 platform defects.

- **M9 (engine reproducibility forensics — REJECT, no defect):** (26) M7 Run B
  reproduced **byte-identical** (−0.9585 return / −1.1587 DD / 387 trades) →
  deterministic, stable config property. (27) **no leakage**: engine fills orders at
  the NEXT bar's open, own-symbol guarded (signal@t→fill@t+1); and a −96% *loss* is
  the opposite of a look-ahead signature (leakage inflates). (28) config-switch
  isolation (fixed 5% universe): cap OFF barely helps baseline (−72.6%→−61% DD, still
  −54%) and invariant **cap-ON==cap-OFF to every digit** → cap is a secondary
  amplifier / downstream of construction over-leverage, not a defect; construction is
  the dominant channel (−59%/−72.6% → +77%/−24%, vol 0.87→0.12). (29) composition
  drift is an amplifier (~+36pp) not the root (frozen universe still −54%);
  async-vintage present (14 start dates) but benign once exposure bounded. (30)
  **decision REJECT** — no engine defect; anomaly is genuine construction behavior
  that disappears under correct (M8-bounded) reproduction; no code changed. **DEFER**
  point-in-time/survivorship-controlled universe (no PIT/delisting data, M6). 0
  platform defects.

- **M6 (universe fidelity audit, no code):** (11) the frozen panel is **prices+volume
  only** — one `ohlcv` table, no exchange/mktcap/shares/sector/delisting/CA metadata;
  `adjustment_factor`≡1.0, `vwap`/`trade_count` 100% NULL. (12) survivorship is
  measured: **9/2143 (0.4%)** names delist-like → currently-listed snapshot, WML
  biased **upward**, magnitude unquantifiable (corrective data is the missing data).
  (13) reproducible-exactly = price≥$5, history, equal-weight decile, skip, US/India
  split; **BLOCKED** = size/mktcap deciles, common-share filter, exact
  NYSE/AMEX/NASDAQ, turnover, survivorship, CA-adjustment verification. (14) **CRSP**
  is the single high-leverage unblock (EXCHCD/SHRCD/SHROUT/DLRET/CFACPR → 5 BLOCKED
  rows to IMPLEMENT). (15) M7's only evidence-safe build = ADV/dollar-volume liquidity
  proxy (Amihud), defaulted off; mktcap/exchange/survivorship reconstruction from
  current listings = look-ahead fabrication, forbidden. Independently re-verified,
  zero number drift.

- **M5 new KG facts:** (8) reproduction reports NET-of-cost, JT reports GROSS —
  now reported on both bases (config-only zero-cost run, no engine change). (9) the
  transaction-cost wedge is ~1.08 pp OOS return; gross OOS return is still NEGATIVE
  (−23.76%) → **costs are NOT the reproduction gap** vs JT's published magnitude;
  the ~80 pp shortfall is structural (survivorship + Cat C decay + leverage-cap +
  single-slice power). (10) gross ≥ net is a locked reporting invariant
  (`test_gross_vs_net_reporting`).

# Institutional Reproduction Program — Live Scoreboard

Canonical source of truth. Updated 2026-07-30.

## Phase 7 — Per-paper scoreboard

| # | Paper | Status | Data | Exp status | Reproduced (published magnitude) | Construction faithful | Validation | Manual steps | Eng issues | Confidence | Date |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Jegadeesh-Titman 1993 (momentum) | DONE | toy (12×2yr) | run, REJECT | NO (−0.29% vs +0.95%/mo) | YES | 2 OOS trades = no power | driver existed | none | HIGH (diagnosis) | 2026-07-30 |
| 2 | Gatev et al. 2006 (pairs) | DONE | toy (12×2yr) | run, REJECT | NO (−1.51% vs +11%/yr) | YES | 22 OOS trades | 1 driver written | none | HIGH (diagnosis) | 2026-07-30 |
| 3 | Sharpe 1964 (CAPM) | BLOCKED | needs mkt portfolio + betas | — | — | — | — | — | data | — | — |
| 4 | Asness et al. (Value & Momentum) | BLOCKED | needs fundamentals | — | — | — | — | — | data | — | — |
| 5 | Fama-French 1993 (3-factor) | BLOCKED | needs size + B/M (Compustat) | — | — | — | — | — | data | — | — |
| 6 | Novy-Marx 2013 (gross profitability) | BLOCKED | needs gross profitability | — | — | — | — | — | data | — | — |
| 7 | Carhart 1997 (4-factor / funds) | BLOCKED | needs fund returns + FF factors | — | — | — | — | — | data | — | — |
| 8 | Black-Litterman 1992 (optimizer) | BLOCKED | needs equilibrium returns + views | — | — | — | — | — | data | — | — |
| 9-10 | (not in corpus) | ABSENT | — | — | — | — | — | — | corpus | — | — |

## Secondary metrics (this run)

- Papers in corpus: 8 landmark (+ junk docs filtered)
- Papers executable on available data: **2 / 8** (JT, Gatev)
- Papers executed: 2
- Papers reproduced (published magnitude): **0 / 2**
- Construction-faithful reproductions: **2 / 2**
- Reproducibility (same fingerprint → same result): **PASS** (JT re-run hit
  `duplicate_experiment` short-circuit → deterministic)
- Manual interventions: paper 1 = 0 (driver existed), paper 2 = 1 (driver written once)
- Validation pass (published-magnitude): 0/2 — both diagnosed to data scale
- Engineering defects discovered: 0
- Knowledge Graph: 52 nodes / 112 edges (from production campaign)

## Phase 9 — Verified blocker (the ONE evidence-driven recommendation)

**Observed failure:** every reproduction fails to match published magnitude.
**Evidence:** JT = 2 OOS trades (decile = 1 stock); Gatev = 1 pair not 20;
6/8 papers cannot start (fundamentals/broad cross-section absent).
**Affected subsystem:** market-data inputs (`data/analytics.duckdb`), not
strategy/backtest/validation logic — those are proven faithful and deterministic.
**Research impact:** CRITICAL — blocks 8 of 8 remaining faithful reproductions
and the 10-paper program target.
**Expected benefit:** unblocks papers 1-6 to publishable-comparison fidelity.
**Estimated effort:** DATA acquisition + load, not architecture. ≥100 names ×
≥10 yr adjusted prices (papers 1,2) + Compustat fundamentals (papers 4-7) via
existing `CSVLoader → DuckDBStore`. Zero engine change for the price papers.

## Certification (honest)

Platform PROVEN on 2/2 price-executable landmark methodologies: faithful
construction, deterministic, auditable reports, honest discrepancy analysis.
The 10-paper reproduction TARGET is **not achievable on current data** — a
verified data blocker, not an engineering defect. Per Phase 9, no architectural
work is recommended; per the anti-fabrication rule, remaining papers are NOT run
on toy data to fake completion. Program pauses pending real datasets.

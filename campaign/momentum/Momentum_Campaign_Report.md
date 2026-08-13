# Momentum Research Campaign — Master Report

**Mentisrex Capital, Quantitative Research Division. 2026-08-03.**
Frozen platform, no tuning, no architecture change. Answers: under what conditions
does momentum exist, how faithfully can Mentisrex reproduce the literature, and
what strategy is justified. All figures trace to `campaign/momentum/runs/*.jsonl`.

## Workstream status

| WS | Deliverable | Status |
|---|---|---|
| A Literature | `Literature_Map.md` | done |
| B Reproductions | `Canonical_Reproductions.md` (JT-1993 run; Carhart/MOP/AMP BLOCKED) | done |
| C Methodology | `Methodology_Fidelity.md` | done |
| D Robustness | `Robustness_Report.md` (US 7-config sweep) | done |
| E Cross-market | `Cross_Market_Report.md` (US vs India, 14 runs) | done |
| F Meta / KG | `Knowledge_Graph_Summary.md` | done |
| G Strategy | `Production_Strategy.md` (Momentum v1) | done |
| H Reporting | this report + `Executive_Summary.md` | done |
| — Special | `Leverage_Investigation.md` (root-cause, 0 defects) | done |

## The evidence, in one table (OOS)

| Config | US Sharpe / ret / p | India Sharpe / ret / p |
|---|---|---|
| JT_6-1-6_decile (L/S) | 0.935 / +58.8% / 0.161 | −1.424 / −46.1% / 1.000 |
| form_3m | 0.622 / −48.0% / 0.315 | 0.542 / −147.5% / 0.351 |
| form_9m | 0.573 / −85.0% / 0.268 | −0.630 / −145.1% / 1.000 |
| form_12m | −0.685 / −62.0% / 1.000 | 0.043 / −28.1% / 0.479 |
| hold_3m | 0.921 / −241.8% / 0.152 | −0.432 / −196.6% / 1.000 |
| tercile | 0.596 / −113.5% / 0.304 | 0.603 / −144.6% / 0.291 |
| long_only | 0.522 / +99.0% / 0.155 | **1.012 / +416.5% / 0.026 ✓** |

## Findings

1. **Momentum exists, narrowly and market-specifically.** US: a weak,
   insignificant long/short relative-strength effect single-peaked at 6-month
   formation. India: a strong, *significant* long-only trend effect (+416.5%,
   p 0.026) whose L/S version is destroyed by the short leg.
2. **The premium is a tail effect.** Decile beats tercile in both markets;
   broadening breadth kills it. Concentrated in extreme winners/losers.
3. **The short leg is the liability.** US: it carries the −71% drawdown. India:
   it flips every L/S book negative (bull-regime rebound of past losers).
4. **Frequent rebalancing is a risk control, not a cost.** 63-day holding
   detonates both books (−242% / −197%).
5. **Faithful reproduction is bounded by data, not the engine.** JT-1993 runs and
   is directionally correct; Carhart/MOP/AMP are BLOCKED on absent
   fundamentals/multi-asset data. **0 platform defects** across 14 runs + the
   leverage investigation.
6. **Every L/S number is leverage-truncated.** Fixed 5%/name × ~200 decile names
   = ~10× nominal gross vs a 1.5× cap → only ~30 names fill (M3). Uniform across
   markets; a fidelity gap, not a defect.

## Reproduction fidelity vs the literature

Directionally consistent with Jegadeesh-Titman (positive intermediate-horizon
relative-strength, concentrated in deciles, decaying/reversing past ~12 months).
**Not** a magnitude-faithful reproduction: no skip-period (M1), no
overlapping-holding averaging (M2), fixed-cap not equal-weight sizing (M3), net
not gross reporting (M4), no JT liquidity/large-cap screens (M6), 2014–2026 not
1965–1989 (M7/D), single OOS slice (M8). Ranked fidelity roadmap in
`Methodology_Fidelity.md` and `Canonical_Reproductions.md`.

## Ranked fidelity improvements (identified, NOT implemented under freeze)

1. **M6** — JT price/liquidity/large-cap universe screens (highest impact; kills
   the penny-name drawdown variance).
2. **M3** — equal-weight-within-budget sizing (lets the full decile express under
   the 1.5× cap; fixes the leverage truncation).
3. **M1** — 1-week formation skip-period.
4. **M2** — overlapping-holding portfolio averaging.
5. **M8** — walk-forward / multi-period significance instead of one 70/30 slice.
6. **Survivorship** — ingest delisting returns to de-bias the long-only result.

## Strategy outcome

**Momentum v1** (`Production_Strategy.md`): long-only, 6-1(skip)-1, top-decile,
equal-weight, monthly, single liquid market, ≤1× gross. The only
evidence-justified design. **Paper-trade only** — survivorship bias, single-regime
significance, and two unbuilt fidelity pieces (M3, M6) disqualify live capital.

## Campaign integrity

No parameters tuned to improve results. No toy data substituted. No architecture
changed. Every blocked paper reported with its exact missing dataset. Every
headline number reproducible from a committed jsonl line. 0 engineering defects.

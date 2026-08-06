# Institutional Reproduction Program — Live Scoreboard

Canonical source of truth. Updated 2026-08-03 (momentum campaign).

## Phase 7 — Per-paper scoreboard

| # | Paper | Status | Data | Exp status | Reproduced (published magnitude) | Construction faithful | Validation | Manual steps | Eng issues | Confidence | Date |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Jegadeesh-Titman 1993 (momentum) | DONE | **real US+India daily 2014–26** | run, REJECT | **directional** (US OOS +58.8% WML, Sharpe 0.935, p 0.161; not sig) | YES | 345 US OOS trades (real power) | driver reused | none | HIGH | 2026-08-03 |
| 1b | JT extension — momentum campaign (14 runs, US+India robustness/cross-market) | DONE | **real US+India** | 14 run: 1 ACCEPT / 13 REJECT | India long-only **significant** (+416%, Sharpe 1.012, **p 0.026**) | YES | up to 1076 OOS trades | grid driver | none | HIGH | 2026-08-03 |
| 2 | Gatev et al. 2006 (pairs) | DONE | **real US+India daily 2014–26** | 14 run, REJECT | NO — edge decayed (US −5.7%/−1.08 Sh, India +8.7%/−0.43 Sh vs +11%/yr) | YES | **3999 US / 3303 India OOS trades** (real power) | grid driver | none | HIGH | 2026-08-04 |
| 2b | Do & Faff 2010/2012 (pairs decay) | DONE (directional) | real US+India | via pairs campaign | **supported** — our 0/14 decay-to-reject *is* their finding | YES | 14 runs | grid driver | none | HIGH | 2026-08-04 |
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

## M12 — Low-Volatility campaign (2026-08-06)

New alpha family (Haugen-Baker / Blitz-van Vliet total-volatility anomaly), long
low-vol / short high-vol decile, price-only panel. **Certification: REJECT.**

- Canonical investigate: OOS +20.89%, OOS Sharpe 0.176, **adjusted p = 0.366 → reject**.
- Continuous full-sample: +84.98% return but **max DD −103.35% (ruin)**; short high-vol
  leg blows up under NAV-proportional sizing + 1.5× gross cap (same mode as momentum).
- Robustness/deploy variants: **0 / 8** clean-positive-non-ruined. Ruin persists across
  quantile (q_20 −127%), estimator (downside −160%), and at zero cost (cost drag ~4pp,
  not the killer). `lb_504` history-starved (0 trades). lb_126 / liq_50 cleanly negative.
- Capacity (India ₹): long leg deployable (₹16 cr floor), **short leg bottleneck
  ₹0.27 cr** → L/S undeployable; long-only indicated.
- Engineering defects: **0** (engine sound per M9; ruin is genuine strategy behavior).
- Strategy: **NONE** funded. Long-only low-vol + CRSP/Compustat unblock gate any revisit.
- Artifacts: `campaign/lowvol/` (Final_Report, Registry, Lessons_Learned, Literature,
  Implementation, capacity_india.json, shards/).

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

## Phase — Momentum Campaign update (2026-08-03)

The Phase 9 data blocker is RESOLVED for the price-executable momentum family: a
real US+India daily panel (2014–2026, 2143 symbols) was ingested. JT-1993 now
runs on real data with genuine OOS power (345 US trades, not 2), and a 14-run
robustness + cross-market campaign extends it. Full artifacts under
`campaign/momentum/` (Momentum_Campaign_Report, Cross_Market_Report,
Robustness_Report, Production_Strategy, Leverage_Investigation, Executive_Summary).

- Momentum runs executed: **14** (7 US + 7 India), no tuning, one OOS split each.
- Statistically significant (adj p < 0.05): **1 / 14** — India long-only decile
  (+416.5%, Sharpe 1.012, p 0.026).
- Directional-positive but insignificant: US JT decile L/S (+58.8%, p 0.161).
- Construction-faithful: YES (same frozen `FactorStrategy`); magnitude-faithful:
  NO (fidelity gaps M1/M2/M3/M6/M8 identified, not implemented under freeze).
- Engineering defects: **0** (incl. a full leverage root-cause investigation →
  Category B methodology/M3, not a defect).
- Still BLOCKED (data, honest): Carhart 1997, MOP 2012, AMP 2013 — need
  fundamentals / multi-asset panels; NOT run on toy data.
- Strategy: Momentum v1 = long-only 6-1-1 top-decile equal-weight monthly, single
  market, ≤1× gross — **paper-trade only** (survivorship + single-regime caveats).

## Phase — Momentum Sequential Fidelity update (2026-08-04)

Sequential single-change methodology campaign (M1→M4) on the canonical JT US
panel, engine frozen, no tuning. Each step isolates one JT-1993 construction
element and is KEEP/REJECT-certified on OOS risk-adjusted evidence + fidelity.

| Step | Isolated change | OOS Sharpe | OOS trades | Adj p | Decision |
|---|---|---|---|---|---|
| M1 | equal-weight decile L/S | −0.687 | 848 | 1.000 | baseline |
| M2 | + $5 price screen (JT-2001) | +0.098 | 672 | 0.424 | KEEP |
| M3 | + overlapping cohorts (JT-1993) | +0.006 | 4781 | 0.495 | **BLOCKED** (engine NAV-% vs dollar-hold; verified, not a defect) |
| **M4** | **+ 1-month skip (JT-1993)** | **+0.112** | **593** | **0.413** | **KEEP** |

- **Institutional baseline = M4**: `FactorStrategy(lookback=126, quantile=0.10,
  rebalance_days=21, allow_short=True, equal_weight=True, min_price=5.0, skip=21)`,
  `max_position_pct=1.0`. Artifacts: `campaign/momentum/m{1,2,3,4}/`.
- M4 verdict is still engine-REJECT (single-slice p-gate; nothing clears α=0.05 —
  power limit, not economic). Baseline promotion is the separate fidelity+OOS
  decision: OOS Sharpe ↑ (+0.098→+0.112), turnover ↓ 12%, fidelity restored.
- M4 root-cause: all differences Category A (fidelity: OOS Sharpe, turnover) or D
  (regime: IS collapse; sub-1.5 pp OOS return/DD noise). **Engineering defects: 0.**
- M3 remains BLOCKED, not revisited; unblock = dollar-hold position mode
  (engine unfreeze). See `campaign/momentum/m3/M3_Fidelity_Report.md` +
  `Leverage_Investigation.md`.

**M5 — gross vs net reporting fidelity (2026-08-04).** Audit: reproduction reports
**net**-of-cost (commission 10bps + spread 5bps + slippage); JT-1993 reports
**gross**. They differ → surfaced the gross-comparable metric by running the M4
baseline under a zero-cost config (config-only, no engine/strategy/stats change).

| Basis | OOS return | OOS Sharpe | OOS DD | Trades | Adj p |
|---|---|---|---|---|---|
| NET (production, M4) | −24.84% | +0.1124 | −77.24% | 593 | 0.4134 |
| GROSS (JT-comparable, M5) | −23.76% | +0.1165 | −77.14% | 589 | 0.4103 |

- **Decision: KEEP M5** — gross now reported alongside net (JT-comparability);
  net production metrics preserved; 595 tests pass; 0 forbidden-surface change.
- **Cost wedge = ~1.08 pp OOS return.** Gross OOS return still **negative** →
  transaction costs are NOT the reproduction gap; the ~80 pp shortfall vs JT is
  structural (survivorship + Cat C decay + leverage-cap + single-slice power).
- Institutional baseline **strategy** unchanged (M1+M2+M4); M5 is a reporting
  standard: every reproduction reported on both bases. See
  `campaign/momentum/m5/M5_Fidelity_Report.md`.

## Phase — Momentum M6 Investable-Universe Fidelity Audit (2026-08-05)

Institutional data-availability audit of the frozen panel (`data/analytics.duckdb`,
one `ohlcv` table). **No production code / methodology / filter / parameter changed;
595 passed, 2 skipped — all baselines reproducible.** Every figure re-verified by an
independent agent against the raw DB (zero drift). Full report:
`campaign/momentum/m6/M6_Investable_Universe_Fidelity_Audit.md`.

- Panel = **prices+volume only**: 2143 symbols (US 1016 · India `.NS` 1127),
  2014–2026 daily. **Absent:** exchange, market cap, shares outstanding, sector,
  delisting flag, corporate-action table. `adjustment_factor`≡1.0; `vwap` +
  `trade_count` 100% NULL.
- **Survivorship quantified:** only **9/2143 (0.4%)** names delist-like →
  currently-listed snapshot → WML biased **upward** (HIGH), magnitude unquantifiable.
- **Reproducible exactly:** price≥$5 (M2), sufficient history, equal-weight decile
  (M1), 1-month skip (M4), US/India split, gross/net (M5).
- **BLOCKED (metadata, not code):** market-cap/size deciles, common-share filter,
  exact NYSE/AMEX/NASDAQ membership, turnover, survivorship correction, CA-adjustment
  verification.
- **IMPLEMENT PROXY (defensible):** ADV / median ADV / dollar-volume liquidity screen
  (Amihud precedent). **Not** acceptable: current exchange↦historical, current
  shares↦historical mktcap, any manufactured survivorship fix.
- **Single high-leverage unblock = CRSP** (`EXCHCD`/`SHRCD`/`SHROUT`/`DLRET`/`CFACPR`
  → converts 5 BLOCKED rows to IMPLEMENT). **M7 roadmap:** optional ADV/dollar-volume
  universe filter (evidence-gated, default off) + formalized US/India partition; **no**
  reconstruction of mktcap/exchange/survivorship (would be look-ahead fabrication).
- Engineering defects: **0.** The reproduction gap is confirmed **data-fidelity**
  (survivorship + missing metadata), costs already ruled out (M5).

## Phase — Momentum M7 Liquidity Filter (2026-08-05) — REJECT

Implemented the one M6-approved universe improvement: a generic liquidity screen
from close+volume only (`src/aurelius/research/liquidity.py`, metric registry:
median/mean dollar volume, ADV, Amihud; default = median dollar volume). Wired into
`FactorStrategy`, **default OFF** → on_bar byte-identical to M4 when disabled.
Two runs only (net, US OOS), pre-registered pct=0.20/window=21 (no sweep). Full
report: `campaign/momentum/m7/M7_Liquidity_Filter_Report.md`. Records:
`us_jt_m7_runA.jsonl` (baseline), `us_jt_m7_runB.jsonl` (+filter).

| Metric | Run A (baseline) | Run B (+liquidity) |
|---|---|---|
| OOS Sharpe | +0.1124 | +0.2767 |
| OOS Return | −24.84% | **−95.85%** |
| OOS Max DD | −77.24% | **−115.87%** (blow-up) |
| OOS Trades | 593 | 387 |
| Adjusted p | 0.4134 | 0.2952 |

- **Run A = committed M4 to every digit** → certified baseline unchanged, deterministic.
- **Decision: REJECT.** The screen optically lifts Sharpe (+0.164) and p (−0.118)
  but craters OOS return (−71 pp) and breaches a **>100% drawdown**. KEEP is
  conjunctive (defensible AND economically supported AND integrity-preserving); the
  economic + integrity gates fail. Feature left **default OFF**; baseline stays
  **M1+M2+M4**.
- Root cause: universe shrinkage → smaller decile count → larger equal-weight
  per-name strength → 1.5× leverage-cap concentration blow-up (Category B, L5/M3).
  **0 platform defects.** Fair re-test needs dollar-hold / fixed-N sizing (M3 unblock).
- Framework **retained in code, disabled** — correct and reusable; 596 passed, 2 skipped.

## Phase — Momentum M8 Portfolio Invariance Framework (2026-08-05) — ADOPT

Portfolio-construction-only campaign (objective = invariance, not performance).
Diagnosed the M7 concentration channel: incumbent weight `budget/_count`
(`_count=int(quantile·n)`) makes single-name concentration `∝1/n`. Implemented
bounded equal-weight (`src/aurelius/research/portfolio_construction.py`:
`min(budget/max(count,n_min), w_max)` — constant-gross + single-name cap +
min-constituent floor), wired into `FactorStrategy` as `invariant_construction`,
**default OFF** (w_max=0.10, n_min=10). Full report:
`campaign/momentum/m8/M8_Portfolio_Invariance_Report.md`. Records:
`invariance_probe.json`, `us_jt_m8_confirm.jsonl`.

**Exposure probe (deterministic, all shrink levels):**

| design | max single-name weight (785→15 names) | HHI range |
|---|---|---|
| baseline | 0.96% → **75%** (×78) | ×78 → 1.125 |
| invariant | 0.96% → **7.5%** (×7.8) | bounded ≤0.079 |

Baseline == invariant **exactly for f≥0.25** → certified baseline unchanged unless
the universe is severely reduced. Below the n_min floor the invariant book
de-levers gross (1.5→0.15) rather than concentrating.

**End-to-end confirmation (5% shrink, 50 names, only construction varies):**

| Metric | baseline | invariant |
|---|---|---|
| OOS Return | −54.06% | +20.17% |
| OOS Max DD | **−77.63%** | **−21.88%** |
| OOS Trades | 19 | 229 |

- **Decision: ADOPT** bounded equal-weight as the standard portfolio-construction
  framework for all future universe-reducing campaigns (exchange/market-cap/
  survivorship/liquidity filters). Default OFF; mandatory when a campaign shrinks the
  universe. Strategy baseline unchanged (M1+M2+M4) — M8 is a construction-layer
  standard (as M5 was a reporting standard). 597 passed, 2 skipped.
- **Honest scope:** M7's 20% blow-up was ABOVE the ~10% concentration crossover
  (max weight ~1.2% there) → driven by async-vintage/composition/leverage-cap
  (engine-level, frozen), not snapshot concentration. M8 bounds the concentration
  channel it controls; the rest needs synchronous rebalance + dollar-hold sizing
  (M3 unblock). 0 platform defects.

## Phase — Momentum M9 Engine Reproducibility & Vintage Audit (2026-08-05) — REJECT (no defect)

Forensic audit of the M7 anomaly (OOS −95.85% / −115.87% DD). Read-only tracing +
config-switch isolation; **no signal/factor/portfolio/cost/reporting/ingestion
change, no code correction required.** Report:
`campaign/momentum/m9/M9_Engine_Reproducibility_Audit_Report.md`. Records:
`m7_repro_runB.jsonl`, `m9_isolation.json`.

- **Phase 1:** M7 Run B reproduced **byte-identical** (−0.0321/0.2767/−0.9585/
  −1.1587/387/0.2952) → deterministic, stable config property.
- **Phase 2 (leakage):** none. Engine fills at the NEXT bar's open, own-symbol
  guarded (signal@t→fill@t+1). A −96% *loss* is the opposite of a leakage signature.
- **Phase 3 (composition):** drift is an amplifier (~+36pp: −96%→−54% when frozen)
  not the root; frozen 50-name book still −54%. PIT & survivorship-controlled
  universes **DEFERRED** (no as-of-date/delisting data, M6).
- **Phase 4 (isolation, fixed 5% universe):**

| construction | cap | Return | Max DD | Vol | Trades |
|---|---|---|---|---|---|
| baseline | 1.5× | −59.2% | −72.6% | 0.87 | 44 |
| baseline | 1000× (off) | −54.0% | −61.0% | 0.51 | 211 |
| invariant | 1.5× | +77.3% | −24.1% | 0.12 | 194 |
| invariant | 1000× (off) | +77.3% | −24.1% | 0.12 | 194 |

  Cap OFF barely helps baseline; invariant **cap-ON==cap-OFF exactly** → cap is a
  secondary amplifier, not a defect. Construction is the dominant channel;
  async-vintage benign once exposure bounded.
- **Decision: REJECT** — no engine defect; the M7 anomaly is genuine
  construction-driven exposure behavior that disappears under the correct M8-bounded
  reproduction. M7 stays REJECTED, M8 bounded construction stays ADOPTED — together
  they fully account for the anomaly. **0 platform defects.** 597 passed, 2 skipped.

## Phase — Momentum M10 Capacity & Liquidity Deployability Audit (2026-08-05) — REJECT

Deployability audit of the corrected strategy (M4 + M8 invariant construction).
Frozen signal/factor/construction/data/benchmark; varied only execution/liquidity/
scaling. No product code (analysis scripts only); 597 passed, 2 skipped. Report:
`campaign/momentum/m10/M10_Capacity_Liquidity_Audit_Report.md`. Records:
`shards/*.jsonl`, `capacity_india.json`.

- **P1 turnover** (cadence 21/28/42/84d): turnover 1.41→0.50, trades 1540→251, hold
  94→150d — but **every full-universe config breaches 100% drawdown** (ruin;
  full-sample continuous single-capital sim).
- **P2 liquidity** (drop bottom 25/50/75% by median $vol + M8 construction):
  risk-controlled (DD −61/−63/−69%) but **negative returns −10.3%/−23.4%/−42.3%**,
  worsening with tighter filter.
- **P3 capacity** (India ₹): ceiling ₹46cr (median decile name ≤10% ADV) collapses to
  **₹0.41cr** on the illiquid decile tail — capacity vs alpha conflict.
- **P4 cost** (gross→high): cost drag **~4pp**, trivial vs **−81.5% gross** → alpha
  absent, not cost-killed (consistent with M5 gross-negative).
- **Decision: REJECT** — alpha does not survive realistic execution; strategy not
  deployable. Not a platform defect (M9: 0 defects), not a retraction of M1–M9.
  PIT/survivorship DEFERRED (M6/M9 data) but biases performance upward → strengthens,
  never reverses, the REJECT.

## Phase — Momentum M11 Research Termination & Alpha Retirement (2026-08-05) — ARCHIVE

Termination/archival campaign (docs + statistical synthesis + reproducibility
verification only; no code, no new runs; 597 passed, 2 skipped). Deliverables:
`campaign/momentum/Momentum_Evidence_Summary.md`, `Momentum_Retirement_Decision.md`,
`Momentum_Final_Postmortem.md`, `Momentum_Future_Roadmap.md`.

- **Evidence synthesis (M1–M10):** internally consistent; two apparent contradictions
  (India long-only p=0.026; US WML +58.8%) resolve to confound + evaluation-basis. 0
  platform defects across the program.
- **Falsification:** hypothesis "cross-sectional price momentum on 2014–2026 price-only
  data is deployable alpha" is **FALSIFIED** — direct falsifiers: M5 gross OOS negative
  (no alpha at zero cost), M10 deployment ruin + negative liquidity-filtered returns,
  0/14 significance. Supporting evidence insignificant (US slice) or confounded (India).
- **Uncertainty:** Cat A resolved (~0); Cat B wrong-direction (survivorship correction
  *worsens* momentum, ≲0.05); Cat C = different alpha hypotheses. No credible reversal.
- **Decision: ARCHIVE.** Retire the price-momentum signal on this dataset. Keep the
  platform (0 defects) and adopted standards (M2 $5 screen, M4 skip, M5 dual reporting,
  M8 bounded construction). Highest-leverage next action = acquire **CRSP + Compustat**;
  runnable-now roadmap = low-vol > residual-momentum > mean-reversion.

**Momentum program status: CLOSED (ARCHIVE). M12 = new alpha family, selected from the
roadmap after M11 certification.**

## Phase — Pairs Campaign update (2026-08-04)

The 2026-07-30 Gatev toy blocker (12 names, 22 trades, no power) is RESOLVED: a
12-month Gatev formation window on the real US+India panel yields 864–1127
complete-history names → a genuine top-N distance-pair book. Gatev now runs with
real power and a 14-run robustness/cross-market campaign extends it. Full artifacts
under `campaign/pairs/` (Pairs_Campaign_Report, Canonical_Reproductions, Robustness,
Cross_Market, Production_Strategy, Methodology_Fidelity, Executive_Summary).

- Pairs runs executed: **14** (7 US + 7 India), no tuning, one OOS split each.
- Statistically significant (adj p < 0.05): **0 / 14** — every config REJECT, all
  adjusted p = 1.000, every OOS Sharpe negative.
- Reproduction: Gatev construction-faithful (SSD 12-mo formation, top-N portfolio,
  2-SD entry / convergence exit) with genuine power (3999 US / 3303 India OOS trades
  on the canonical) — the published ~11%/yr premium **does not survive to 2014–2026**
  (Class D market evolution, per Do-Faff).
- Engineering defects: **0.** The top40 blow-up (−60% US / −42% India) is the
  fixed-% sizing + 1.5× gross-cap truncation breaking dollar-neutrality — Class B
  (P5/M3), a documented fidelity gap, not a defect.
- Still BLOCKED (data/selector, honest): Vidyamurthy cointegration, Avellaneda-Lee
  PCA/ETF OU, Kalman dynamic hedge, sector-matched (Do-Faff refinement),
  cross-country/ADR — need selectors/data absent from the frozen platform.
- Strategy: **NONE.** 0/14 significant → no evidence-justified production pairs
  strategy; naming a config would be tuning. Recommend not funding further pairs
  engineering; gate any revisit behind P5 sizing + P3 rolling re-formation + a
  delisting-returns dataset.

## M13 — Long-Only Low-Volatility campaign (2026-08-06)

- Runs: **6** long-only (1 canonical full + 5 robustness cont) + 1 analytic capacity.
  Only change vs certified M12 baseline: `allow_short=False`. Framework/engine/execution/
  M8/data pipeline frozen.
- Canonical: IS +46.12% (Sharpe 0.017) / OOS +36.19% (Sharpe 0.609, DD −7.4%);
  continuous +172.98%, Sharpe 0.31, DD **−36.26% (no ruin)**, turnover 0.19, 783 trades.
- Statistically significant (adj p < 0.05): **0 / 1** — adjusted p = 0.1182, verdict
  reject. ~3× closer to the gate than M12's 0.366 but not significant.
- Robustness: **4/5 live variants clean positive non-ruined**; liquidity filter improves;
  lb_504 starved (data limit). No ruin anywhere — decisive contrast to M12's 0/8.
- Capacity (India ₹, long leg only, budget 1.0): ceiling **₹12.19 cr p10** / ₹830 cr
  median. No short-leg bottleneck — deployable.
- Engineering defects: **0.** Short-leg ruin diagnosis from M12 confirmed by its absence.
- Certification: **DEFER** — deployable, robust, promising, but statistically uncertified
  and alpha-vs-beta undecomposable (no factor model, M6). Unblock = CRSP/Compustat +
  longer OOS. Not a production strategy yet; not a rejected one either.

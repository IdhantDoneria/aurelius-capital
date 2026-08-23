# Mentisrex (existing) vs. "US Equity Systematic Programme v3.0" — Comparison Audit

Date: 2026-08-21
Scope: theoretical/mechanism comparison only, per request — no backtest run, no numbers independently verified.
Source documents: this repo (`docs/`, `campaign/`, `src/mentisrex/`) as of commit `c2ccfbb`; user-supplied
`US_Equity_Systematic_Programme_v3_Full_Specification.md` ("v3 spec" below).

---

## 0. Headline finding

**These are not two versions of the same strategy — they are two different things being compared.**

- The v3 spec describes a **fully specified, single, integrated 10-sleeve levered long/short book**, with a named
  production package (`sysq`, 13 modules, 21 invariant tests) that the document says ships alongside it.
- Mentisrex has **no certified or live strategy of any kind**. Every sleeve tested (11 momentum variants, 2 low-vol
  variants, 14 pairs configs) is REJECTED, ARCHIVED, or DEFERRED. No cross-sleeve combined book has ever been
  built or certified here — each family was tested in isolation.
- **The `sysq` package does not exist in this repository.** Grep for `sysq` across every `.py`/`.md` file returns
  zero hits. The spec is a standalone document; the code it repeatedly cites (`sleeves.py`, `allocator.py`,
  `risk.py`, `execution.py`, the 18–21 invariant tests) was not supplied and cannot be inspected, audited, or run.
  Every number in the spec is therefore a **claim**, not a verifiable artifact — which the document itself
  concedes ("Backtested means hypothetical... produced by the author, with full knowledge of what happened").

So the honest comparison is: an unfinished, self-skeptical research programme that has certified nothing yet,
against a polished, complete-looking specification for a strategy whose code is absent and whose results cannot
currently be reproduced or checked in this environment. Everything below compares them on mechanism and stated
philosophy, not on whose numbers to trust.

---

## 1. Current state / maturity

| | Mentisrex (this repo) | v3 spec ("sysq") |
|---|---|---|
| Status | Nothing certified. Best case is M13 (long-only low-vol), verdict **DEFER** — fails its own 5% significance gate (adj. p = 0.1182) | Presented as production-ready: "every mandate target is met," staged deployment plan, governance calendar |
| Code present in this env | Yes — full pipeline, inspectable | No — package `sysq` referenced but not delivered |
| Live/paper trading | Infra built (`src/mentisrex/paper/`, Alpaca-wired) but **nothing currently instantiates it in production** — no cron/entrypoint | Document describes a live daily runner (`cli.py run --mode paper/live`) but no code to confirm it exists or behaves as described |
| Self-assessed confidence | Low by design — the roadmap's own thesis is "information gain is DATA-limited," i.e. the pipeline has hit a wall it cannot currently pass | High rhetorically ("headline... every mandate target is met") but paired with an unusually thorough self-critique section (13 drawbacks, kill criteria, forward-haircut stack down to 12–18% CAGR) |

---

## 2. Universe & data

| | Mentisrex | v3 spec |
|---|---|---|
| Instruments | 2,143 tickers: US 1,016 + India 1,127 (`.NS`) | 657 US tickers, median 593 eligible, single market |
| Data source | Yahoo Finance OHLCV, free tier | Not named explicitly, but explicitly flagged as free-vendor-quality: "Free data vendors do not retain delisted securities" |
| Fields available | Price + volume only. No shares outstanding, sector, market cap, delisting flag, corporate-action table. `vwap`/`trade_count` are 100% NULL | Same constraint — "Daily OHLCV only" is stated as a hard mandate boundary (Table 1), not a gap |
| Backtest window | 2014–2026 (per-campaign windows vary; M14 regression uses 2015-01-05 → 2026-07-30, 2,890 obs) | Jul 2017 – Aug 2026, 9.1 years, 2,295 trading days |
| Survivorship bias | Quantified at 0.4% of the panel showing delisting-like patterns (9/2,143 names) → acknowledged as biasing returns upward, **magnitude not estimated, not corrected** | Deliberately seeded ~150 delisted tickers, only 6 returned usable history — 98% survivor-constituted. **Magnitude is estimated** (0.5–1.5 pts/yr central case, up to 3.2 pts/yr in Section 11 stress) and a specific $500/yr fix is named (Norgate/Sharadar/CRSP) |
| Verdict on this dimension | Same underlying weakness (no point-in-time delisting data, no fundamentals) as v3 — **but v3 quantifies the cost and prices a fix; Mentisrex flags it and stops there.** |

**Convergent finding worth flagging on its own:** both documents independently reach the same structural
conclusion. Mentisrex's newest roadmap states the pipeline's ceiling is "DATA-limited, not idea-limited" — no
factor model is possible without shares-outstanding/fundamentals data. The v3 spec's Section 15.3 ("the only route
to a materially higher Sharpe") names the identical missing pieces — earnings/PEAD data, short interest, and
fundamental quality/value data — as the highest-value additions, explicitly *not* solvable by "cleverer
mathematics on the same inputs." Two independently-produced documents agree the bottleneck is data acquisition,
not signal research.

---

## 3. Signal philosophy

| | Mentisrex | v3 spec |
|---|---|---|
| Signal families tested | Cross-sectional momentum (JT 1993, 9 variants), low-volatility (long/short and long-only), pairs trading (Gatev 2006, 14 configs) | 10 sleeves across 3 conceptual families: 4 directional/timing (trend, vol-managed exposure, breadth, vol-term-structure reversal), 4 cross-sectional momentum variants (12-1, residual, information-discreteness, relative-volume), 2 cross-sectional mean-reversion (illiquidity premium, short-horizon reversal) |
| Combination across families | **Never attempted.** Each family (momentum, low-vol, pairs) was researched, tested and certified/rejected as a standalone strategy. There is no code path that combines a momentum sleeve with a low-vol sleeve into one book | Central to the design — this *is* the strategy: 4 directional sleeves averaged into a "core," 6 satellite sleeves averaged into a "satellite," combined additively before a shared gross cap |
| Momentum's fate | **Archived / falsified.** M11's verdict: cross-sectional price momentum on this 2014–2026 price-only panel is not deployable — 0/14 configs significant, gross-negative OOS, full-universe configs breach >100% drawdown (ruin) under continuous simulation | Momentum family (S5/S6/S7) is retained but the document itself flags it as **the weakest diversification story in the book** — S5/S6/S7/S9 correlate 0.70–0.98, "three sleeves, one bet," and only 3 of 10 sleeves individually clear t=2 |
| Low-vol's fate | Long/short version **rejected** (canonical OOS Sharpe 0.176, adj p=0.366, and −103% max DD = ruin on the short leg). Long-only version **deferred**, not certified | Not present as a named sleeve — v3 has no low-volatility/betting-against-beta sleeve. Notably, the v3 spec **tested and explicitly rejected** low-vol/low-beta/low-lottery-demand (Section 3.4): "sorting the universe on beta produced 30.2% for the highest-beta quintile against 12.0% for the lowest" — i.e., v3's own data says low-vol *inverted* over 2017–2026. This is a direct, testable point of tension with Mentisrex's M12/M13 low-vol work, which was run on a different, overlapping-but-not-identical universe and period (2014–2026, US+India) and reached a different (though still non-certified) result. Neither side's numbers should be taken as settling this without a controlled, same-universe/same-period re-test. |
| Pairs/stat-arb | Rejected 14/14, attributed to published-anomaly decay since 2006 | Directly corroborated: v3's own Section 3.4 rejects PCA statistical arbitrage (Avellaneda-Lee) on the same logic — "the paper itself reported degradation after 2003... there is no residual mean reversion to harvest." Independent agreement between the two documents. |

---

## 4. Portfolio construction

| | Mentisrex | v3 spec |
|---|---|---|
| Method actually certified/used | Bounded equal-weight: `weight = min(budget / max(count, n_min), w_max)`, single-name cap 10% NAV, `n_min` floor of 10 names. Adopted 2026-08-05 after M7 showed unbounded concentration (max weight hit 75% NAV, HHI 1.125) | Two-tier: equal weight *within* each of the core/satellite groups (no fitted parameters there), then two multipliers (`k_c=4.00`, `k_s=3.60`) calibrated *across* the two groups — the only two parameters described as genuinely fitted in the whole construction |
| Cross-sleeve combination | Not implemented — no allocator exists that merges independently-tested sleeves into one weight vector | Core-satellite sum, `RAW = CORE + SATELLITE`, is the load-bearing mechanism of the entire design |
| Generic infra available but unused by certified work | `src/mentisrex/construction/`: signal aggregation (z-score blend), 3 sizing schemes (equal-weight, vol-target, risk-parity), 3 optimizers (min-variance, max-Sharpe, constrained min-variance), exposure limits module (per-name/sector/gross caps). None of this was routed through by the certified M-series campaigns — it's parallel scaffolding, not the production path | N/A — v3 has one specified construction method, not a menu |
| Position caps | Single-name 10% NAV (research infra allows configuring higher); no separate benchmark/index cap concept | Two explicit tiers: 20% single-name cap, 300% cap on the index instrument specifically — the spec calls this out as a fix for a defect where a benchmark instrument was wrongly bound by the single-name limit |
| Gross exposure cap | 1.5× on long/short campaigns (momentum, low-vol); 1.0× (no leverage) on the long-only M13 book | 2.75× hard cap, binding on 96% of days by design, asserted by a named unit test (`test_gross_cap_never_breached`) — not present in this codebase to verify |
| Net exposure | Long-only book (M13) is fully net long by construction (~1.0×); long/short campaigns target near-neutral | Average net ~1.30× (long 2.02×, short 0.72×) — this is a directionally levered book, not market-neutral, despite having a "market-neutral" satellite layer |

---

## 5. Leverage & risk management

| | Mentisrex | v3 spec |
|---|---|---|
| Max gross leverage | 1.5× (long/short) or 1.0× (long-only, unlevered) | 2.75× (with staged rungs from 1.0× to 3.0× described) |
| Circuit breakers | Kill switch, daily loss limit (3% of SOD equity), drawdown halt (20% peak-to-trough), position cap (10% NAV), gross leverage cap (1.5×), liquidity/participation cap (20% ADV), single-trade stop-loss budget (2% NAV), sector cap (30%), HHI cap (20%) — **9 controls, no severity tiering** | 13 named breakers with 3 severity tiers (SOFT / DERISK / HALT): drawdown warn/derisk/halt at 20/28/34%, daily-loss warn/halt at 5/10%, vol ceiling, gross-hard, net-hard, position-hard, turnover-spike, data-stale, universe-collapse, cost-divergence |
| Deployment ramp / staged capital increase | Not present as a formal mechanism in the risk engine | Explicit: 1.00× → 1.75× → 2.25× → 2.75×, one rung per quarter, enforced by a described `effective_cap()` reading persisted state |
| Sleeve-level degradation handling | Not present — a failing sleeve has no defined fallback in the code reviewed | Explicit fallback table (Section 9): a sleeve whose rolling 12-month Sharpe drops below −1.0 for 3 months is halved, never zeroed, with a stated rationale and a measured cost of that choice |
| Kill criteria (pre-committed, quantitative stop conditions) | Not found as a formal artifact in this repo — verdicts (REJECT/ARCHIVE/DEFER) function as after-the-fact research gates, not live-trading kill switches | Explicit table of 8 pre-committed kill criteria (realized vol/turnover/beta out of band, cost divergence, correlation creep, drawdown ≥34%, 3 years below 0.3 Sharpe, invariant test failure) |
| Verdict | Mentisrex's risk controls are real, coded, and tested, but narrower in scope and not built around a staged-deployment or sleeve-decay philosophy. v3's risk framework is more elaborate **on paper** — none of it is verifiable here since the code isn't present. |

---

## 6. Execution & cost modeling

This is the single largest *mechanical* asymmetry between the two, and it cuts in different directions on
different sub-points.

| | Mentisrex | v3 spec |
|---|---|---|
| Order types | `MARKET`, `LIMIT` only — no MOC type in the codebase | Market-on-close (MOC) exclusively, order entry deadline 15:50 ET |
| Signal-to-fill lag | T+1 open (signal at bar *t*, fill at next bar's open), certified look-ahead-free by an M9 forensic audit | 2 trading days (signal from close of t−1, order at close of t, return from t to t+1) — and the spec is unusually candid that this exact lag choice swings CAGR by 3–5 points and is "the programme's largest single fragility" |
| Transaction cost assumption | Commission 10bps + spread 5bps + slippage 10bps ≈ **25bps one-way**, described as an Almgren-Chriss-style model | **5bps one-way**, i.e. Mentisrex's own cost assumption is markedly more conservative than v3's headline assumption. (v3 does stress-test up to 40bps and shows the strategy breaks around there.) |
| Financing cost (margin interest, stock-borrow fee, short-rebate credit) | **Not modeled anywhere in the codebase.** Grep for `borrow`, `financing`, `margin_interest`, `short_rebate`, `stock_loan` returns nothing relevant — only an unrelated leverage-cap comment | Modeled explicitly and is the *second-largest* cost in the strategy: 3.14% annual drag (4.10% margin interest + 0.29% borrow fee − 1.25% rebate credit), computed daily against a policy-rate path |
| Verdict | Mentisrex under-models financing cost entirely (a real gap — v3's own document calls this the single most common omission in published backtests: "most published backtests of levered long/short books omit the second component entirely," and that critique applies squarely to Mentisrex's current code). Mentisrex over-models (i.e. is more conservative on) per-trade transaction cost. Net effect on any hypothetical combined/levered Mentisrex book is unclear without doing the actual work — flagging both gaps rather than netting them out. |

---

## 7. Statistical rigor & certification bar

| | Mentisrex | v3 spec |
|---|---|---|
| Formal promotion gates | `PromotionEngine`: paper-trading requires Sharpe ≥ 0.5, adjusted p-value ≤ 0.05, TC breakeven ≥ 30bps, walk-forward consistent. Relaxed "further validation" tier at Sharpe ≥ 0.3 / p ≤ 0.10 | No equivalent formal engine described; qualitative narrative instead (t-stats per sleeve, DSR, kill criteria) |
| Multiple-testing correction | Present — every campaign verdict quotes an *adjusted* p-value, and this adjustment is what pushes M13 into DEFER (raw signal looks better than the adjusted one) | Deflated Sharpe Ratio (DSR) computed against assumed trial counts up to 20,000 — reported to survive (DSR probability 0.663 even at that count) |
| Bootstrap / path resampling | Not identified as a standard tool in this repo's reviewed modules | 10,000-path stationary block bootstrap (21-day blocks) — reports 5th-percentile CAGR (13.8%), 5th-percentile max drawdown (−48%), and P(drawdown > 40%) = 18.9% |
| Walk-forward | Used as one of the 5 certification dimensions per campaign (majority-of-folds-positive check in `robustness.py`) | Described as year-by-year with no refitting (Table 21) |
| Parameter sensitivity | `robustness.py` has TC/slippage sweeps and rolling-stability decay checks | 51-configuration, 12-parameter whole-portfolio re-optimization grid, with the claim that production sits at the *median* rather than the *maximum* of each swept range — offered as evidence against overfitting |
| Forward-expectation haircut | Not present as a formal stacked adjustment in the reviewed docs | Explicit stacked haircut from 28.4% backtest CAGR down to a stated 12–18% "honest forward expectation," Sharpe 0.65–0.85 |
| Verdict | Mentisrex's rigor is real and is what's producing the (mostly negative) verdicts — it is why nothing has been certified yet. v3's rigor is more elaborate in the document, including the DSR/bootstrap/haircut apparatus that Mentisrex doesn't currently have implemented — but again, none of it is checkable here without the `sysq` code. |

---

## 8. Self-disclosed weaknesses (a direct comparison of what each side admits)

Both documents are unusually candid for research/strategy writeups, which is worth noting on its own. Key
overlaps and differences:

- **Both admit the core signal problem is diversification, not signal quality.** Mentisrex: "information gain is
  DATA-limited, not idea-limited." v3: effective breadth is 4.05 "of a nominal 10" and this — not any individual
  sleeve's Sharpe — is named as the binding constraint on the whole book's quality.
- **Both admit survivorship bias is present and unresolved-to-fully-resolved.** v3 at least prices it
  (0.5–1.5 pts/yr) and names a $500/yr fix; Mentisrex flags it on every verdict without pricing it.
- **v3 admits its return is mostly beta, not alpha:** "two thirds of its return is levered beta... in a decade
  when beta was unusually well paid," with the alpha component isolated at +9.8 points and quantified separately.
  Mentisrex has no combined book to make an equivalent decomposition on.
- **v3 admits it doesn't hedge, it amplifies** (downside beta 1.09, loses more than the index in 3 of 4 material
  drawdowns) — a materially different risk posture than a market-neutral or low-vol defensive design, despite
  having sleeves labeled "market-neutral." This is worth flagging explicitly since a reader skimming "6
  market-neutral sleeves" might assume defensive behavior that the document itself says isn't there at the
  book level.
- **Mentisrex's rejections are final in a way v3's self-criticism isn't.** M11 formally *archived* momentum as
  falsified for this data/period. v3 *keeps* three momentum-family sleeves (55–60% of the satellite layer's
  correlation mass) while acknowledging they're "three ways of saying 'buy winners, sell losers.'" Same underlying
  concern, opposite resolution — Mentisrex killed the signal, v3 kept it and sized around its weakness.

---

## 9. What would be needed to make this a real, checkable comparison

Since the user asked for a theoretical/mechanism comparison only, no backtest was run and no number from either
side was independently verified. To turn this into a decision-grade comparison rather than a document-vs-document
read, in order of leverage:

1. **Get the `sysq` code.** Nothing in Section 7's rigor claims (DSR, bootstrap, invariant tests) or Section 6's
   execution model can be checked without it. Right now the v3 numbers are exactly as verifiable as the document
   says its own backtest is: "hypothetical... produced by the author, with full knowledge of what happened."
2. **Same universe, same period, same cost assumptions.** v3 (657 US names, 2017–2026, 5bps) and Mentisrex
   (2,143 US+India names, 2014–2026, 25bps) are not comparable as-is. The low-vol disagreement in Section 3 in
   particular cannot be resolved without this.
3. **Price Mentisrex's missing financing-cost model.** This is the one clean, actionable code gap this audit
   surfaced — v3's own document argues it's usually the largest single omission in this class of backtest, and
   it is currently fully absent from `src/mentisrex/`.
4. **Decide whether Mentisrex wants a v3-style integrated core-satellite book at all**, versus its current
   philosophy of certifying single sleeves independently before ever combining them. This is a design-philosophy
   choice, not a data gap, and it's the largest structural difference between the two approaches.

---

## Known limitations of this audit itself

1. **Skipped: verifying any v3 spec number against code.** Reason (impossibility): the `sysq` package the spec
   describes is not present anywhere in this repository or its history — confirmed by an exhaustive grep.
   Unblock: obtain the `sysq` source alongside the spec.
2. **Skipped: resolving the low-vol contradiction (Section 3).** Reason: the two low-vol results (Mentisrex M12/13
   vs. v3 Section 3.4) were produced on different universes and periods; adjudicating which is "right" requires a
   controlled re-test, which the user asked not to run in this pass.
3. **Skipped: netting the transaction-cost vs. financing-cost gaps into a single dollar estimate for a
   hypothetical Mentisrex book at v3-like leverage.** Reason: no combined/levered book exists in Mentisrex to apply
   either cost model to — this would require building the construction layer first, which is out of scope for a
   theoretical comparison.

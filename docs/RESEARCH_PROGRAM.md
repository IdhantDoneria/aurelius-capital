# Mentisrex Capital — Quantitative Research Program

**Owner:** Director of Quantitative Research
**Mandate:** discover statistically robust, economically explainable alpha.
**Constraint:** platform is complete. Build no new infrastructure unless a hypothesis is blocked by a genuine capability gap. Output of this org is *validated alpha*, not software.

This document is the research constitution. It defines what we research, how an idea travels from paper to capital, and what stops a bad idea from ever consuming a second cycle. It reuses the existing platform: `mentisrex.research.models` (`Verdict`, `ValidationReport`, `ValidationCriteria`, `ExperimentRecord`, `dataset_fingerprint`), `mentisrex.assistant` (paper parsing, hypothesis generation, bias detection, reports), the backtest engine, construction, risk, and paper-trading loop.

---

## 0. Operating principles

1. **Economic rationale precedes statistics.** No alpha enters the pipeline without a written mechanism explaining *who* is on the other side of the trade and *why* they persistently lose. A t-stat without a story is a data-mining artifact.
2. **Reject early, reject cheap.** Kill order is fixed: economic story → cost survival → OOS → multiple-testing correction → fragility. A hypothesis that dies at step 1 must never reach a backtest.
3. **Every result is guilty until proven robust.** Default verdict is REJECT. INCONCLUSIVE and REJECT are successes — they cost pennies and protect capital.
4. **Nothing is retested by accident.** Every hypothesis, pass or fail, lands in the knowledge base with its `dataset_fingerprint` and verdict. Re-proposal of a known-dead idea is auto-flagged.
5. **Breadth over cleverness.** Fundamental law: `IR ≈ IC · √breadth`. A mediocre signal applied to 3000 names beats a brilliant one applied to 5. Prioritize ideas that scale across a universe.

---

## 1. Alpha taxonomy

Each category below is a research *lane*. A lane has a fixed economic thesis, a standing dataset requirement, a reusable feature set, a benchmark to beat, and a pre-registered success bar. Success criteria are declared **before** any capital, and are checked by `ValidationCriteria`.

Common success bar (all lanes, net of costs, unless tightened per-lane):
- OOS deflated Sharpe ≥ 0.5 after multiple-testing correction.
- OOS ≥ 60% of in-sample Sharpe (no more than 40% decay).
- Turnover-adjusted: net Sharpe positive after modeled transaction costs + market impact.
- Parameter CV ≤ `ValidationCriteria.max_param_cv` across the plausible parameter neighborhood (fragility gate).

### 1.1 Momentum / trend
- **Economic rationale:** under-reaction to news and behavioral herding; slow diffusion of information; risk-transfer to trend followers. Losers are late-reacting fundamental investors and forced sellers.
- **Datasets:** daily/weekly OHLCV (point-in-time, split/dividend adjusted); index membership history for universe construction.
- **Features:** 3/6/12-month total return skip-one-month, 52-week-high proximity, time-series momentum (own-asset), moving-average crossovers, residual (idiosyncratic) momentum.
- **Benchmark:** cross-sectional 12-1 decile long-short; time-series 12m sign strategy.
- **Success bar:** beat 12-1 net Sharpe by ≥ 0.15; max drawdown not worse than benchmark (momentum crashes are the known failure mode — stress against 2009-style reversals).

### 1.2 Value
- **Economic rationale:** compensation for distress/illiquidity risk and correction of extrapolation errors. Losers are investors overpaying for glamour.
- **Datasets:** point-in-time fundamentals (earnings, book, sales, cash flow) with correct reporting-lag; price. **Survivorship-free** universe is mandatory here.
- **Features:** B/M, E/P, FCF yield, EV/EBITDA, sales/price; sector-neutralized composites.
- **Benchmark:** HML-style B/M decile long-short, sector-neutral.
- **Success bar:** positive net alpha after controlling for market + size; must survive a value-drought subsample (2017-2020) at INCONCLUSIVE-or-better, not REJECT.

### 1.3 Quality / profitability
- **Economic rationale:** mispricing of persistence in profitability; investors under-weight durable margins.
- **Datasets:** point-in-time fundamentals (ROE, gross profitability, accruals, leverage).
- **Features:** gross profits/assets, ROE, ROIC, accruals (Sloan), earnings stability, debt/equity.
- **Benchmark:** QMJ-style composite long-short.
- **Success bar:** low correlation (|ρ| < 0.3) to existing value/momentum lanes — quality earns its slot only if it diversifies.

### 1.4 Low volatility / low beta
- **Economic rationale:** leverage-constrained investors overpay for high-beta lottery names; the low-risk anomaly is the residual.
- **Datasets:** daily returns for realized vol/beta; OHLCV.
- **Features:** trailing realized vol, beta, idiosyncratic vol, max daily return (lottery proxy).
- **Benchmark:** BAB (betting-against-beta) construction, beta-neutral.
- **Success bar:** positive net return with lower drawdown than market; must remain positive after financing/leverage cost assumptions (BAB is leverage-sensitive).

### 1.5 Event-driven
- **Economic rationale:** slow price adjustment to discrete corporate events; limits to arbitrage around hard-to-short or index-driven flows.
- **Datasets:** earnings dates + surprises, guidance, M&A, index reconstitution schedules, insider filings, buyback announcements.
- **Features:** post-earnings-announcement-drift (SUE), earnings surprise, index add/delete flags, insider-buy clusters.
- **Benchmark:** PEAD SUE-decile drift over 60 days.
- **Success bar:** event alpha must survive strict point-in-time event timestamps (no announcement-time leakage) and realistic entry (next-open, not event-close).

### 1.6 Macro / cross-asset
- **Economic rationale:** risk premia across the cycle — carry, term, credit, inflation risk transfer. Losers are hedgers paying for insurance.
- **Datasets:** rates, FX, commodity futures curves, credit spreads, macro releases (point-in-time vintages, not revised).
- **Features:** carry (roll yield), term structure slope, cross-asset momentum, macro-surprise indices.
- **Benchmark:** multi-asset carry + trend composite.
- **Success bar:** low correlation to equity lanes; positive in at least two distinct macro regimes.

### 1.7 Microstructure / short-horizon
- **Economic rationale:** liquidity provision premium, order-flow imbalance, temporary price pressure. Losers are impatient liquidity demanders.
- **Datasets:** intraday trades/quotes, order-book snapshots (only if we already have the feed — do **not** build a new feed speculatively; `# ponytail:` gate this lane behind a data-availability check).
- **Features:** order-flow imbalance, short-term reversal, bid-ask bounce, volume-clock features.
- **Benchmark:** 1-5 day short-term reversal decile.
- **Success bar:** net alpha after *aggressive* cost + impact modeling — this lane is where transaction cost kills most edges. Require capacity estimate before any promotion.

### 1.8 Alternative / sentiment (opportunistic)
- **Economic rationale:** information not yet in price — news tone, positioning, textual signals.
- **Datasets:** news/text feeds, positioning data (COT), search/attention proxies — **only if licensed and already ingested.**
- **Features:** news-sentiment score, dispersion, attention spikes.
- **Benchmark:** sentiment-decile long-short.
- **Success bar:** must add orthogonal alpha vs. price-based lanes; high scrutiny for look-ahead in text timestamps.

**Lane discipline:** a new lane is opened only when (a) the dataset already exists in the platform and (b) the economic thesis is distinct from all open lanes. Otherwise the idea belongs inside an existing lane.

---

## 2. Paper → testable hypothesis

Pipeline (uses `mentisrex.assistant.ResearchAssistant`):

1. **Ingest.** `read_paper(text)` → `PaperSummary` (title, abstract, claims, keywords). Human confirms the *central claim* and the *economic mechanism* in one sentence each. No mechanism sentence → paper rejected at intake.
2. **Extract the bet.** Reduce the paper to: signal definition, universe, horizon, rebalance frequency, and the *direction* of the predicted return. If the paper cannot be reduced to a falsifiable directional bet, it is a survey, not a hypothesis.
3. **Generate candidates.** `generate_hypotheses(summary, researcher, limit=5)` → `Hypothesis` list. Each candidate carries a pre-registered null (H0: signal has zero net predictive value).
4. **De-duplicate against the knowledge base** (section 9) before anything else. Known-dead → stop.
5. **Register.** Create `ExperimentRecord` with `dataset_fingerprint` pinned. From here the hypothesis is tracked immutably.

A hypothesis is *testable* only if it states: signal, universe, horizon, entry/exit rule, expected sign, expected magnitude range, and the datasets it needs — all before a backtest runs. Pre-registration is enforced: the `ExperimentRecord` is written *before* results exist.

---

## 3. Hypothesis scoring (prioritization)

Score each registered hypothesis 1-5 on five axes, then rank. This decides queue order; it does **not** grant capital.

| Axis | 1 (low) | 5 (high) |
|---|---|---|
| **Economic conviction** | vague story, no clear loser | named counterparty, durable mechanism |
| **Breadth** | few names / rare event | whole universe, daily |
| **Orthogonality** | high ρ to live/known alphas | uncorrelated, new risk premium |
| **Data readiness** | needs new feed/license | already ingested, point-in-time |
| **Capacity** | tiny, cost-eaten | scales to target AUM |

**Priority = economic_conviction × (breadth + orthogonality + data_readiness + capacity).** Conviction is a multiplier, not an addend — a story-less idea scores near zero regardless of the rest. Ties break toward lower engineering cost (cheapest test first). Queue is re-sorted weekly.

---

## 4. Statistical validation pipeline

Ordered gates. Each gate can only REJECT or PASS-to-next. Verdict comes from `research.models.Verdict`; thresholds from `ValidationCriteria`. Bias flags from `assistant.detect_biases`.

1. **Code review gate.** `review_code(source)` must return `has_lookahead == False`. Any look-ahead / leakage finding (negative shift, future index, fit-on-full-series scaler, bfill, whole-series stats) → REJECT before a single backtest. Non-negotiable.
2. **In-sample sanity.** Signal produces the predicted sign with a plausible raw Sharpe. Wrong sign → REJECT (thesis is falsified).
3. **Cost survival.** Apply transaction costs + market impact (square-root law). Net Sharpe ≤ 0 → REJECT. Most microstructure and high-turnover ideas die here; that is correct.
4. **Out-of-sample.** Walk-forward + holdout (section 6). Requires ≥ `min_oos_observations`. OOS decay > 40%, or OOS Sharpe not distinguishable from zero → REJECT.
5. **Multiple-testing correction.** Deflate Sharpe for the number of trials on this dataset (deflated Sharpe / PBO). Corrected significance must clear `significance_alpha`. This is where most "significant" backtests die.
6. **Fragility / robustness.** Parameter CV ≤ `max_param_cv` across the parameter neighborhood; result stable across subsamples, universes, and reasonable perturbations. `detect_biases` must show no tripped flag. Fragile → REJECT.
7. **Report.** `write_report(record, oos_observations, code_review)` → Markdown research report attached to the `ExperimentRecord`. Verdict is recorded PASS only if all six gates pass.

The assistant advises at every gate. **It never allocates or trades** — enforced structurally (the module imports no execution path; guarded by test).

---

## 5. Rejection rules (hard kills)

An idea is REJECTED — permanently, logged to the knowledge base — on any of:

1. **No economic mechanism.** No named loser, no persistence story.
2. **Look-ahead / leakage** found in code review (any severity that touches the signal timeline).
3. **Wrong-sign** in-sample (thesis falsified).
4. **Negative net-of-cost** return.
5. **OOS decay > 40%** or OOS indistinguishable from zero.
6. **Fails multiple-testing correction** (deflated Sharpe below `significance_alpha`).
7. **Fragile** parameters (CV > `max_param_cv`) or fails a subsample/universe swap.
8. **Insufficient OOS data** (< `min_oos_observations`) — verdict INCONCLUSIVE, parked, not promoted.

Rejections 1-7 are terminal for that formulation. INCONCLUSIVE (8) may be re-queued only when more data exists or the formulation materially changes — and only after knowledge-base check.

---

## 6. Walk-forward & out-of-sample procedures

- **Chronological split, always.** Train on the past, test on the strictly-later future. No random shuffling of time series (the assistant flags shuffle as leakage).
- **Purge and embargo.** Purge overlapping-label observations between train and test; embargo a gap after each train window to kill leakage from serial correlation. (CPCV — combinatorial purged cross-validation — where the label horizon overlaps.)
- **Rolling walk-forward.** Fixed or expanding train window, step forward by the rebalance period, refit, test on the next out-of-sample block. Concatenate OOS blocks into the OOS track record.
- **Final holdout.** A terminal slice of history is untouched until the very end. Touched once. If the idea was tuned against it, it is burned — record that in the fingerprint.
- **Deflation.** Track the number of configurations tried per dataset. Feed that count into deflated Sharpe / PBO at gate 5. Every backtest run on a dataset increments its trial counter — this is what `dataset_fingerprint` protects.
- **Regime coverage.** OOS must span at least one stress regime (drawdown, vol spike, liquidity crunch) via the risk engine's stress module. An alpha that has never seen a bad regime is not validated.

---

## 7. Paper-trading promotion

A PASS verdict earns paper trading, not capital. Uses the existing supervised paper loop (`mentisrex.paper`).

Promotion to paper requires:
1. Verdict PASS on all six validation gates.
2. Signed research report on the `ExperimentRecord`.
3. Capacity + turnover estimate consistent with target AUM.
4. Risk sign-off: position limits, exposure caps, and stress results within mandate.

Paper-trading observation window (minimum, per lane):
- Daily/weekly lanes: **60 trading days** live-paper.
- Event-driven: enough to observe **≥ 30 independent events**.
- Microstructure: **20 trading days** with realized-cost reconciliation.

Paper success criteria (declared before paper starts):
- Live-paper Sharpe within 1 standard error of OOS Sharpe (no fresh decay).
- Realized transaction costs within 25% of modeled costs (else the cost model is wrong — back to gate 3).
- No unexplained risk-limit breaches.
- Journal (`paper.journal`) shows no execution pathology (fills, slippage, timing).

Fail paper → back to research with a written post-mortem in the knowledge base. Paper decay is a common, cheap place to catch overfit that survived backtests.

---

## 8. Production promotion checklist

Capital is allocated only when **every** box is checked:

- [ ] Six validation gates PASS, report signed.
- [ ] Paper-trading window complete, paper success criteria met.
- [ ] Realized vs. modeled cost reconciliation within tolerance.
- [ ] Capacity estimate ≥ intended allocation with margin.
- [ ] Orthogonality confirmed vs. the live book (marginal contribution to portfolio IR is positive; |ρ| to existing sleeves within limit).
- [ ] Risk engine sign-off: VaR, stress, exposure, concentration within mandate at target size.
- [ ] `dataset_fingerprint` shows the final holdout was touched exactly once.
- [ ] Multiple-testing budget for the dataset re-checked at portfolio level (family-wise, not per-idea).
- [ ] Reproducibility: the `ExperimentRecord` re-runs end-to-end and reproduces the reported numbers.
- [ ] Kill switch and monitoring defined: the exact live metric and threshold that pulls the strategy.
- [ ] Initial allocation is a fraction (e.g. ≤ 25%) of target; scale-up gated on live performance matching paper.

Any unchecked box → no capital. Allocation is staged, never all-at-once.

---

## 9. Knowledge management (failed ideas never retested)

The knowledge base is the org's memory. Backed by `research.store` + `ExperimentRecord`.

Every hypothesis — PASS, REJECT, or INCONCLUSIVE — is stored with:
- Hypothesis definition (signal, universe, horizon, rule, expected sign).
- `dataset_fingerprint` (dataset identity + trial count).
- Verdict + the gate that killed it + the deciding statistic.
- Code review findings and bias flags.
- Research report.
- Post-mortem (for paper/production failures).

**Anti-retest mechanism:** at intake (section 2, step 4) every new hypothesis is fingerprinted and matched against the base. A match on (signal family + universe + horizon) that previously hit a *terminal* rejection (rules 1-7) is auto-flagged: retest blocked unless the researcher documents what materially changed (new data, corrected leakage, different mechanism). INCONCLUSIVE ideas surface as "re-queue when data grows," not blocked.

**Second use — meta-research:** periodically mine the base. Which lanes have the highest PASS rate? Which rejection reason dominates (usually multiple-testing or cost)? Which datasets are trial-exhausted (deflated Sharpe budget spent)? This steers the roadmap and prevents flogging a mined-out dataset.

---

## 10. Twelve-month research roadmap + KPIs

Objective: maximize *validated, orthogonal, in-capacity* alpha per research-dollar. Not lines of code. Not backtests run.

### Program KPIs (tracked monthly)
- **Throughput:** hypotheses registered / month (target ≥ 8).
- **Kill efficiency:** % of rejections that die at gates 1-3 (cheap gates). Target ≥ 60% — we want to fail cheap.
- **Yield:** validated (PASS) strategies / quarter (target ≥ 1-2).
- **Survival:** % of paper-promoted strategies reaching production (target ≥ 50%; lower means backtests are overfit).
- **Book quality:** portfolio IR and average pairwise correlation of live sleeves (target: rising IR, ρ staying low).
- **Reproducibility:** % of `ExperimentRecord`s that re-run to the same numbers (target 100%).
- **Anti-retest hits:** count of blocked duplicate proposals (proves the memory works).

### Quarter-by-quarter

**Q1 — Foundation & discipline.**
- Stand up the knowledge base and intake fingerprinting as the mandatory front door.
- Open lanes with data already in hand: momentum, value, quality, low-vol.
- Reproduce 3-4 canonical published anomalies end-to-end as calibration — proves the pipeline reproduces known results before we trust it on novel ones.
- KPI focus: reproducibility 100%, kill efficiency baseline established.

**Q2 — Depth in equity lanes.**
- Push momentum/value/quality to novel formulations (residual momentum, sector-neutral composites, accruals).
- Add event-driven (PEAD, index reconstitution) — highest-conviction event alphas.
- First 1-2 strategies to paper trading.
- KPI focus: throughput ≥ 8/mo, first PASS verdicts.

**Q3 — Orthogonality & first capital.**
- Macro/cross-asset lane for diversification (carry, trend, term).
- First production promotions (staged allocation).
- Portfolio-level multiple-testing budget enforced across the book.
- KPI focus: survival rate, book correlation staying low, first live IR reading.

**Q4 — Scale & mine the base.**
- Meta-research pass: retire trial-exhausted datasets, double down on high-yield lanes.
- Microstructure lane **only if** the intraday feed already exists and capacity justifies it — otherwise defer (YAGNI).
- Scale live allocations where paper matched production.
- KPI focus: validated-alpha yield, rising portfolio IR, kill efficiency ≥ 60%.

### What we explicitly do NOT do
- Build new data feeds, frameworks, or infra speculatively. A lane opens only when its data is already ingested.
- Chase Sharpe with no economic story.
- Re-test terminally-rejected ideas.
- Allocate capital on a backtest alone — paper trading is mandatory.
- Optimize a metric (backtests run, code shipped) that isn't validated alpha.

---

*The engineering platform is a means. The product of this organization is a growing library of economically-grounded, statistically-deflated, capacity-aware alphas — and an equally valuable library of the dead ideas we will never waste time on again.*

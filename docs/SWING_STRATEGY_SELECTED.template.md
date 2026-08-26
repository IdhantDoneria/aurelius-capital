# Mentisrex Capital — Selected Intraday-Signal Swing Strategy

**Document version:** 1.0
**Date:** 2026-08-26
**Classification:** Internal — Strategy & Research
**Package:** `src/mentisrex/swing/`
**Companion document:** [`SWING_PROGRAMME_COMPARISON.md`](SWING_PROGRAMME_COMPARISON.md)

> This document specifies one strategy in enough detail to be implemented,
> risk-managed and monitored without reference to anything else. The
> reasoning behind choosing it over the two alternatives, and the evidence
> that killed those alternatives, is in the companion comparison document.

---

## 1. Recommendation

**Strategy: Nightfall** — a dollar- and beta-neutral US equity book that
holds a cross-sectional position across the overnight gap and is flat during
every session, selected from three candidates on the evidence in the
companion comparison document.

**Recommendation: fund a cost-measurement programme, not a return-seeking
book.**

That distinction is the whole of this document's advice and it is not
hedging. On five years of this firm's own data the strategy earns 1.65 basis
points of edge per round trip against 1.69 basis points of modelled cost — a
ratio of 0.98 — and loses to cash by 0.92% a year. It is short by two
hundredths of the number it needs.

The term it is short by is the weakest measurement in the study. Auction
impact for orders below a tenth of a percent of a name's daily volume is
modelled by extrapolating the square-root law beneath the range it was fitted
on. If true closing-auction impact at that size is about a third of what the
model charges, this strategy clears; if it is not, it does not. The
break-even is at **0.32x modelled costs**, and no backtest can resolve which
side of that line reality sits on. Eight weeks of live fills can.

| | |
|:--|--:|
| Window tested | 2020-03-30 to 2025-01-17, 1,209 sessions |
| Universe | 219 US operating companies, point-in-time, ~200 tradable per session |
| Net CAGR at $50m | 1.63% |
| **Excess of cash** | **−0.92%** |
| Volatility | 1.31% |
| Sharpe | −0.70 |
| Max drawdown | −3.56% |
| Beta to SPY | 0.001 |
| Turnover | 161x a year |
| Edge / cost per round trip | 1.65bps / 1.69bps = **0.98** |
| Cost multiple at which it stops beating cash | **0.32x** |

**Do not deploy this at target size on the strength of these numbers.** They
do not support it. What they support is spending a small, bounded amount to
measure the one input that decides the question.

---

## 2. Economic thesis

A US trading session is two auctions with two different populations, and the
boundary between them is where this strategy lives.

The **overnight segment** — previous close to next open — prices news and
attention. It is where earnings land, where retail order flow accumulates,
and it clears in an opening auction with the widest spreads of the day. The
**intraday segment** — open to close — is where institutional participation
algorithms work, spreading a single decision across hours against a VWAP
benchmark.

Lou, Polk and Skouras (2019, *Journal of Financial Economics* 134:192–213)
document that firm-level returns **continue within each segment and reverse
across them**, and that the profits of a long list of standard strategies
accrue entirely in one segment or the other, usually with opposite signs.
Their interpretation is a tug of war between clienteles that trade at
different times of day.

Measured on this firm's own data over 2020–2025, on 219 US operating
companies, the pattern reproduces:

| Ten-day divergence (intraday minus overnight) predicts | Rank IC | t |
|:--|--:|--:|
| the next **overnight** return | −2.18% | −4.1 |
| the next **intraday** return | +0.73% | +1.6 |
| the next **close-to-close** return | **−0.07%** | **−0.2** |

Read the third line. A name whose recent gains were earned intraday while its
overnight tape lagged gives most of that back overnight and keeps drifting up
during the session, and **the two legs cancel almost exactly**. The effect is
large and significant in the segments and invisible in their sum.

The practical consequence dictates the entire design: **a close-to-close
strategy on this signal earns nothing, however good the signal is.** Any
backtest that marks positions from one close to the next would report this
signal as worthless. It is not worthless — it is segment-specific, and
capturing it means holding one segment and not the other. That is why this
book enters in the closing auction, exits in the next opening auction, and is
flat during every session.

It is also the source of the strategy's central difficulty. Isolating a
segment means trading twice a day, and the segment it isolates is worth about
the same as the two auction crossings it takes to reach.

---

## 3. Universe and eligibility

The strategy trades US-listed common equities on NYSE, NASDAQ and NYSE
American, screened monthly on information available at the ranking date:

| Filter | Threshold | Reason |
|:--|:--|:--|
| Price | ≥ $5.00 | Fees are per share, so a low-priced name is structurally expensive: at $0.0010 a share a $15 stock pays 0.67bps where a $75 stock pays 0.13bps. The one-cent tick floor compounds this — a $10 stock cannot trade inside 10bps however liquid it is. |
| Liquidity | trailing 60-session **median** dollar volume ≥ $5m | Median rather than mean, so a single index-rebalance day cannot promote a name into the universe. |
| History | ≥ 120 sessions | Every signal here is a trailing statistic; a name without history has no signal, only noise. |
| Membership | persists to the next monthly ranking | A name is never in the universe on the strength of liquidity it acquired later. |

Membership ends when a name's bars stop, not when a present-day screen drops
it. The symbol pool is drawn from the broker's **inactive** asset list as
well as its active one, so names that were liquid in 2021 and delisted in
2023 are in the 2021 universe: 184 of the 2,144 names that ever entered the
ranked universe stopped trading before the end of the sample.

**Index products are excluded.** Every claim above is about a single company
— clientele segmentation across *its* overnight and intraday sessions. An ETF
satisfies none of it, and an ETF tracking the index the book is neutralised
against is a hedge wearing a stock's clothing. Left in, they also distort
selection: a screen ranked by dollar volume promotes large ETFs ahead of
every operating company.

Detection is positive — match the fund, not the company. Keeping only names
the broker describes as "Common Stock" fails, because that suffix is applied
inconsistently: Apple has it, Boeing and Bank of America do not. Of the 295
names in the intraday panel, 76 are index products and are dropped, leaving
**219 operating companies** and a median of about 200 tradable on any
session.

That cross-section is thinner than is ideal for a market-neutral book. It is
a direct consequence of the intraday data limits in §14 and not a design
choice.

---

## 4. Signal specification

### 4.1 The two segment returns

For name *i* on session *t*, from split- and dividend-adjusted prices:

```
overnight_i,t  =  ln( open_i,t  /  close_i,t-1 )
intraday_i,t   =  ln( close_i,t /  open_i,t   )
```

These are the two primitives. Everything else is built from them.

### 4.2 Accumulation and scaling

Accumulate each over a lookback of `L` sessions (L = 5 selected on the design
window; 5, 10 and 21 were tested), and scale each by its own trailing
volatility:

```
ON_i,t  =  ( sum over L of overnight_i )  /  ( sigma_overnight,i  *  sqrt(L) )
ID_i,t  =  ( sum over L of intraday_i  )  /  ( sigma_intraday,i   *  sqrt(L) )
```

where the sigmas are 60-session standard deviations of the respective
segment returns, computed strictly before *t*.

**Scaling each component by its own volatility before differencing is not
cosmetic.** Overnight and intraday returns have materially different
variances, and a raw difference of the two is dominated by whichever is
noisier — an overnight signal wearing a spread's clothing.

### 4.3 The score

```
divergence_i,t  =  rank_normal( ID_i,t )  -  rank_normal( ON_i,t )
persistence_i,t =  z( fraction of the last 10 sessions with intraday_i > 0 )

score_i,t       =  divergence_i,t  +  0.25 * persistence_i,t
```

`rank_normal` maps the cross-section to approximately standard-normal scores
by rank. It is used in preference to a raw z-score because both accumulations
have fat tails, and a single outlier would otherwise take over the book.

The persistence term rewards a steady drift over one large day: a name whose
intraday leg was positive on eight of the last ten sessions is a different
proposition from one that had a single large session and nine flat ones.

### 4.4 Direction

**The book is short high divergence and long low divergence, held overnight.**
That sign is read directly off the measured cross-period reversal in §2
(IC −2.18%, t = −4.1), stated in advance, and never fitted.

### 4.5 Eligibility gates

A name is suppressed on session *t* if any of the following holds:

| Gate | Threshold | Why |
|:--|:--|:--|
| Scheduled earnings | within 3 sessions | An earnings gap fills the overnight leg with information rather than clientele flow, which is the opposite of what the signal is trying to read |
| Overnight gap | \|gap\| > 3 trailing standard deviations | The same contamination from unscheduled news |
| Price | < $5.00 | Fees are per share; the tick floor alone can exceed the edge |
| Illiquidity | top 20% by Amihud measure | The book cannot reach these names at the participation cap |
| Security type | any index product | §3 |

The earnings gate needs a **forward-looking** calendar. In backtest the last
three sessions of the sample are conservatively suppressed because that
lookahead is unavailable at the end of a historical file; in live use the
forward calendar exists and this does not arise. The signal-generation CLI
refuses to emit a book in that window rather than returning an empty one that
looks like a flat signal.

---

## 5. Portfolio construction

The score from §4 becomes a book through the shared overlay below. Three
settings are specific to this strategy and were chosen on the design window
(2020-03-30 to 2023-03-31), never on the period after it:

| Parameter | Value | Note |
|:--|--:|:--|
| Lookback `L` | 5 sessions | 5, 10 and 21 tested |
| Per-name participation cap | **0.01% of the name's trailing daily dollar volume** | The binding constraint; see §6 |
| Per-name weight cap | 1.5% of equity | Rarely binds once the participation cap is applied |
| Volatility target | 10% annualised | Nominal, not binding — see §6.0 |
| Gross cap | 3.0x | |
| Holding | 1 session, no staging | The signal refreshes daily, so staging would hold stale positions |

The walk-forward chose the 0.01% participation cap in **all three folds**,
and the lookback varied only between 5 and 10. Parameter stability of that
kind is the useful diagnostic — a walk-forward that lands on a different
corner of the grid each year is reporting noise.

### 5.1 The shared overlay, in order

```
raw score
  -> winsorise at 3 robust (MAD-scaled) standard deviations
  -> neutralise against: intercept, market beta, size, momentum, volatility
  -> scale to unit gross
  -> volatility target
  -> gross cap
  -> per-name cap, alternated with re-neutralisation, three passes
  -> drawdown brake
```

Three details that are easy to get wrong and were got wrong once each during
construction:

**The per-name cap is a limit on equity, so it must be applied to the sized
book.** Capping a unit-gross vector and renormalising afterwards — the
obvious implementation — removes the cap entirely, because the
renormalisation undoes exactly what the clip did. A test now asserts that a
single dominant score cannot take the whole book.

**Capping perturbs neutrality, so capping and neutralising are alternated.**
Three passes, with a final clip that guarantees the cap holds. Residual net
exposure after the final clip is reported by the simulator rather than
assumed to be zero.

**Volatility targeting is two-pass, not a feedback controller.** Pass one
runs the book at fixed unit gross and records its daily return; pass two
uses a trailing estimate of that unit-gross volatility as the sizing
denominator, computed only from returns up to the previous session.

No sector classification exists in this data set. Size, momentum and
volatility loadings serve as a statistical sector proxy — the leading
components of a daily equity return matrix are dominated by sector
structure, and neutralising these three removes most of it. This is a
substitute, not an equivalent, and is listed among the limitations.

---

## 6. Leverage policy

### 6.1 What binds, and why it matters more than the target

The 10% volatility target on this book is **decorative, and the document says
so rather than quoting it as if it were achieved.**

A dollar-neutral, beta-neutral, style-neutral book of roughly 200 US
large-caps that carries only the overnight leg has an unlevered volatility of
about **1.65% a year**. Reaching a 10% target would require roughly **six
times gross exposure**. Reg-T permits about two times overnight. The target
is unreachable by a factor of three before the participation cap is even
considered.

What actually sets size is the **participation cap**, and it is the single
most consequential parameter in the strategy. Its effect is not the obvious
one:

| Per-name cap | Gross CAGR | Excess of cash | Avg gross | Turnover |
|:--|--:|--:|--:|--:|
| uncapped | higher | materially negative | ~1.0x | ~500x |
| 0.10% of ADV | higher | materially negative | ~1.0x | ~500x |
| **0.01% of ADV** | lower | **least negative** | ~0.5x | 161x |

Capping *reduces* gross alpha and *improves* net return, because market
impact is **concave in order size**. Halving a position divides its impact by
roughly the square root of two while leaving the edge per unit of notional
untouched, so the ratio improves as the book shrinks. This is the opposite of
the intuition that a good signal should be traded harder, and it is why
Nightfall is viable-adjacent at 0.01% of ADV and clearly loss-making
uncapped.

The price is scale. At the cap the book deploys about half its equity, so its
contribution to a fund is `cash rate + alpha` rather than a return on
fully-invested capital.

### 6.0 What sets size here

Three limits bind in sequence, and it matters which one is doing the work on
any given day:

1. **The volatility target**, applied to a trailing estimate of this book's
   own unit-gross volatility.
2. **The gross cap**, which binds whenever the volatility target is
   unreachable.
3. **The per-name participation cap**, a fraction of each name's own daily
   dollar volume — which for a short-horizon book is usually the binding
   constraint and is the one that determines whether the strategy pays for
   its own turnover.

Which one is binding can be read off the simulator's daily output: gross
pinned at the cap means the volatility target is unreachable, gross well
below it with the drawdown brake inactive means the participation cap is
doing the work, and gross moving with realised volatility means the target is
actually binding.

A book persistently at its gross cap has a decorative volatility target, and
should be re-specified rather than left to imply a risk appetite it cannot
express. That is the case for the overnight sleeves here, and §6.1 says so
rather than quoting a 10% target the book has never reached.

### 6.1 Why leverage cannot rescue a negative-alpha book

Worth stating explicitly, because it is the first lever an inexperienced
reader reaches for. Both gross P&L and traded notional are proportional to
gross exposure, so net return is `G x (alpha_rate - cost_rate)`. If the
bracket is negative, every increase in `G` makes the loss larger. Leverage
scales an edge; it does not create one.

The corollary matters more: **turnover cost is an absolute drag, so the
achievable volatility of the book is what must be large enough to pay it.**
A dollar-neutral, roughly 450-name US large-cap book carrying only the
overnight leg has an unlevered volatility of about **1.65% a year** — it
would need roughly **six times gross** to reach a 10% volatility target,
which is not available overnight under Reg-T. Low volatility and high
turnover is the worst quadrant a short-horizon strategy can occupy, and it
is where two of the three candidates sat.

---

## 7. Risk management

### 7.1 Position and exposure limits

| Limit | Value | Enforced where | Why this one |
|:--|:--|:--|:--|
| Per-name weight | 1.5% of equity | Overlay, final clip | A hard ceiling on single-name error, applied to the *sized* book so volatility targeting cannot lift a name through it |
| Per-name participation | fraction of the name's own trailing dollar volume | Overlay, jointly with the weight cap | The control that actually governs impact. A weight cap limits exposure to the fund; only a participation cap limits exposure to the *name's liquidity* |
| Gross exposure | 3.0x equity | Overlay, after volatility targeting | Binds whenever the volatility target is unreachable, which for this book is most of the time |
| Net exposure | dollar-neutral by construction | Overlay, neutralisation | Residual net after the final per-name clip is reported, not assumed to be zero |
| Market beta | neutralised on a 60-session trailing estimate | Overlay, neutralisation | Beta estimated only from returns strictly before the decision date |
| Style exposure | size, momentum, volatility neutralised | Overlay, neutralisation | Stands in for a sector classification, which this data set does not have |
| Price floor | $5.00 | Universe screen | Fees are per share; below this the tick floor alone can exceed the edge |
| Drawdown | linear de-risking, floored at 25% of target size | Overlay, daily | See §7.2 |

The order of enforcement matters and is fixed: caps and neutralisation are
alternated for three passes, and the **final** operation is the per-name clip.
That guarantees the cap holds exactly and leaves neutrality approximate,
which is the right way round — a book with 20 basis points of residual net
exposure is a nuisance; a book with an uncapped position is a headline.

### 7.2 Drawdown brake

Exposure is scaled down linearly between a warning drawdown and a full-brake
drawdown, to a floor rather than to zero. A sleeve at zero can never
demonstrate recovery, so the brake reduces size and keeps the book alive to
be judged.

The brake is a genuine determinant of realised risk, not decoration: in the
overnight cross-sectional backtests it was active on 87% of sessions and
held gross near 1.0x against a 3.0x cap. Any reading of those drawdown
figures has to account for the fact that the brake was doing most of the
work.

### 7.3 Financing and borrow

Charged daily, not assumed away:

- margin interest on gross above one times equity, at the overnight rate
  plus 50bps;
- stock-borrow fee of 40bps annual on general collateral and 300bps on the
  least-liquid tradable quintile;
- short rebate credited at the overnight rate less 15bps.

The overnight rate is the actual 13-week bill series. The 2020–2021
zero-rate era and the 2023–2026 high-rate era are materially different
regimes for a levered book, and a fixed rate assumption would misprice this
sample by several hundred basis points a year.

---

## 8. Execution

### 8.0 The daily cycle

| Time (ET) | Action |
|:--|:--|
| 15:40 | Signal computed from data through 15:45; targets emitted by `python -m mentisrex.swing.cli targets --strategy nightfall --equity <E>` |
| 15:45–15:50 | Book reconciled against current positions; deltas sized; MOC orders staged |
| 15:50 | **MOC cut-off.** Orders must be in. Anything missed is not chased in the continuous market |
| 16:00 | Fills at the closing print |
| overnight | Position held. This is the entire return-generating window |
| 09:28 | MOO orders submitted to flatten the **whole** book |
| 09:30 | Fills at the opening print. Flat until 15:50 |

Two rules that are part of the strategy, not of the operations:

**Nothing is chased.** A missed MOC leaves that name unheld overnight. The
alternative — crossing the spread in the continuous market at 15:55 — costs
several times what the auction does and turns a missed position into a
guaranteed loss.

**The book is flattened completely at the open, every day.** There is no
carry-over. The signal refreshes daily and the intraday segment has the
opposite expected sign, so holding through a session is not a smaller version
of the strategy — it is the cancellation described in §2.

### 8.1 Why both legs are auctions

The closing auction is the cheapest liquidity in the US market — NYSE
reported it matching $55.5bn a day in Q2 2024, 9.44% of consolidated notional
— and an auction fill crosses no spread. On this firm's own intraday data,
**18.1% of regular-hours volume prints in the final thirty minutes.**

The opening auction is not cheap. It is a far smaller event with none of the
close's index contra flow and the widest spreads of the day, and the cost
model charges it **twice** the closing cross's impact coefficient
deliberately. That asymmetry is a real risk to this strategy and is called
out in §13: its exit leg is already the expensive one.

### 8.1 Timing discipline

**A signal dated `d` uses only information observable by 15:45 ET on day
`d`.** The gap between the 15:45 decision price and the actual fill is left
in as genuine execution uncertainty. A signal that only works when it is
both computed *and* filled at the same closing price is not a signal.

For anything evaluated intraday, a rule evaluated on the close of one bar
fills at the **open of the next**. Stops fill at the stop price when the
bar's range contains it, and at the bar's open when the bar gapped through
it, which is the conservative side of that ambiguity.

### 8.2 Cost assumptions this strategy is being held to

| Component | Assumption |
|:--|:--|
| Commission | $0.0010 per share |
| Auction fee | $0.0010 per share (closing/opening cross only) |
| SEC Section 31 | 0.25bps, sales only |
| FINRA TAF | $0.000166 per share, sales only |
| Spread | `1450 x sigma_daily x (ADV in $m)^(-1/3)`, floored at one tick / price |
| Impact | `eta x sigma x sqrt(participation)` above 0.1% of daily volume, linear below |
| eta | 0.50 continuous, 0.40 closing cross, 0.80 opening cross |

The spread is **modelled, not measured** — there is no quote data in this
repository, and both standard high-low estimators were tested and found to
overstate by between 3x and 20x at realistic levels. Every performance
figure in this document is therefore accompanied by a cost sensitivity, and
the breakeven cost multiple is stated.

---

## 9. Expected performance and its decomposition

### 9.1 The headline, stated against the right benchmark

| | Value |
|:--|--:|
| Window | 2020-03-30 to 2025-01-17 (1,209 sessions) |
| Net CAGR | 1.63% |
| **Excess of cash** | **−0.92%** |
| Volatility | 1.31% |
| **Sharpe** | **−0.70** |
| Max drawdown | −3.56% |
| Time under water | 78.7% |
| Longest drawdown | 627 sessions |
| Beta to SPY | 0.001 |
| Alpha t-statistic | −1.6 |
| Newey-West t on excess | −1.67 |
| Skew / excess kurtosis | +0.22 / 12.9 |
| Turnover | 161x a year |
| Average gross | 0.32x |

**The strategy earns 1.63% and loses to cash.** Over this window the average
Treasury bill yielded more than that, and the simulator credits interest on
the roughly two-thirds of equity the participation cap leaves undeployed —
so the CAGR is mostly the bill. The number that matters is −0.92%.

### 9.2 Alpha and beta

Beta to the market is **0.001** and the R-squared against SPY is effectively
zero. This is a genuinely market-neutral book, by construction rather than by
accident: the overlay neutralises an intercept, a 60-session trailing market
beta, and size, momentum and volatility loadings before sizing.

Annualised alpha is **−0.94%** with a t-statistic of −1.6. There is no
positive alpha to report. What there is, is a *gross* return of 1.33% a year
on a book with 1.31% volatility — a gross information ratio near one — that
does not survive its own turnover.

### 9.3 Where the return goes

| Component | Per day, on equity | Annualised |
|:--|--:|--:|
| Gross signal P&L | +0.53bps | +1.33% on equity, +4.14% on deployed gross |
| Trading cost | −0.54bps | — |
| Financing, net of interest on idle cash | +0.66bps credit | — |
| **Edge per round trip** | **1.65bps** | |
| **Cost per round trip** | **1.69bps** | |
| **Ratio** | **0.98** | |

The first two rows are the strategy in miniature: half a basis point of
signal a day against half a basis point of trading cost. The third row — the
credit on the two-thirds of equity the participation cap leaves in cash — is
larger than either, which is why the CAGR is positive and the excess return
is not.

Read the last three rows. Two auction crossings cost 1.69 basis points, and
the overnight segment they buy access to is worth 1.65. Everything else in
this document is commentary on that.

### 9.4 Year by year

| Year | Return | Excess Sharpe |
|:--|--:|--:|
| 2020 (from March) | −1.83% | −2.23 |
| 2021 | −1.04% | −0.90 |
| 2022 | +0.97% | −0.61 |
| 2023 | +4.30% | −0.85 |
| 2024 | +5.29% | **+0.14** |

The improving *return* column is mostly the rising bill rate. The Sharpe
column is the strategy, and it beat cash in one year of five.

### 9.5 Sampling uncertainty

A stationary block bootstrap of the **excess** series, 4,000 paths, mean
block ten sessions:

| | Excess Sharpe |
|:--|--:|
| Realised | −0.70 |
| Bootstrap 5th percentile | −1.42 |
| Bootstrap median | −0.72 |
| Bootstrap 95th percentile | −0.02 |
| **P(excess Sharpe < 0)** | **95.5%** |

The 95th percentile does not reach zero. On its own sampling distribution,
this strategy is below cash in nineteen of twenty resamples.

The deflated Sharpe, adjusted for 34 configurations examined, is **0.0001**
against a deflation benchmark of 1.08 — which is the arithmetic saying what
the table above already says.

### 9.6 Regimes and out-of-sample

| VIX regime | Sessions | Excess (ann.) | Sharpe | NW t |
|:--|--:|--:|--:|--:|
| low | 614 | −0.66% | −0.61 | −0.97 |
| mid | 220 | +0.01% | +0.01 | +0.01 |
| high | 126 | −0.90% | −0.42 | −0.33 |

No regime rescues it. The Nagel prediction — that liquidity-provision returns
rise with volatility — is **not** visible here; the high-VIX bucket is no
better than the low. That is a genuine disagreement between this data and the
hypothesis, and it is reported rather than buried.

Walk-forward, three folds, parameters re-chosen each year: **excess −1.31% a
year, Sharpe −1.00**, with fold Sharpes of −1.52, −2.35 and +0.48. The
participation cap was selected identically in all three folds.

---

## 10. Capacity

| Equity | Net CAGR | Excess of cash | Sharpe |
|:--|--:|--:|--:|
| $5m | −1.85% | −4.34% | −1.07 |
| $10m | +0.27% | −2.24% | −0.73 |
| $25m | +1.16% | −1.38% | −0.72 |
| **$50m** | **+1.63%** | **−0.92%** | **−0.70** |
| $100m | +1.50% | −1.06% | −1.25 |
| $250m | +1.71% | −0.86% | −1.93 |

**Capacity in excess of cash: none at any size tested.**

The shape is worth understanding, because it is not the usual one. Excess
return *improves* from $5m to $50m and then deteriorates. At small size the
participation cap does not bind, the book runs at full gross, and it pays
full impact on every name. At $50m the cap binds hard, the book deploys about
a third of equity, and cost per unit of turnover falls faster than edge. Past
$100m the cap binds so hard that what is left is a rounding error on a large
cash balance, and the Sharpe deteriorates because the strategy is a smaller
and smaller share of a portfolio measured against the bill.

There is therefore a genuine optimum near $50m, and it is a loss.

---

## 11. Deployment plan

The ramp below is a **measurement programme, not a capital-raising
schedule.** The single largest uncertainty in this study is the cost model —
the spread is estimated rather than observed, and small-order auction impact
is extrapolated below the range the square-root law was fitted on. Both
resolve in weeks of live trading and in no other way. The ramp is therefore
designed to buy that information at the smallest price that still produces a
statistically usable sample.

| Stage | Duration | Equity | Purpose | Gate to the next stage |
|:--|:--|--:|:--|:--|
| 0. Paper | 4 weeks | — | Confirm the signal pipeline reproduces the backtest book daily, and that orders reach the closing auction before the cut-off | Book matches the backtest to within rounding on 20 consecutive sessions |
| 1. Cost discovery | 8 weeks | 5% of target | Measure realised cost per round trip against the model. Return is not the objective and should not be judged | ≥ 400 fills; realised cost within 1.5x modelled |
| 2. Signal confirmation | 2 quarters | 25% of target | Measure realised rank IC against the backtest estimate | IC t-statistic > 2 on the live sample, and no breach of §12 |
| 3. Half size | 2 quarters | 50% of target | First stage at which return is a legitimate criterion | Rolling excess return above zero, drawdown within model |
| 4. Target | — | 100% | — | — |

Two rules that matter more than the schedule:

**Stage 1 is not judged on return.** Eight weeks of a strategy with this
volatility carries no information about its return — the standard error on an
eight-week Sharpe estimate is larger than the Sharpe itself. Stage 1 exists
to measure *cost*, which converges far faster than return because every fill
is an observation.

**Size is set by participation, not by conviction.** The per-name cap is a
fraction of each name's own daily volume, so the book grows with the
liquidity of the names it holds rather than with the manager's confidence.
Raising the participation cap is a separate decision from raising equity, and
should be taken separately, with its own evidence — the participation sweep
in the comparison document is where the cost of getting it wrong is
quantified.

---

## 12. Monitoring and kill criteria

The point of stating these in advance is that a drawdown is not the moment
to decide what counts as failure.

| Monitor | Frequency | Warning | Action |
|:--|:--|:--|:--|
| Realised vs modelled cost per round trip | Weekly | realised > 1.5x modelled | Halve size; re-estimate the spread model from live fills |
| Rolling 60-session Sharpe | Daily | below zero for 3 consecutive months | Size to 50%, never to zero |
| Drawdown | Daily | brake thresholds in §7.2 | Automatic |
| Net exposure | Per rebalance | above the stated cap | Reject the rebalance, trade to the cap |
| Signal decay (rank IC vs forward segment) | Monthly | IC t-statistic below 2 on a trailing year | Research review before further capital |
| Fill slippage vs decision price | Daily | median above modelled one-way cost | Investigate venue and timing |
| Borrow availability / recall | Daily | any forced buy-in | Reduce short book, review the name's borrow tier |

**Hard stop:** if realised cost per round trip exceeds the edge per round
trip on a trailing quarter, the strategy stops. That is the ratio the whole
thesis rests on, and it is measurable live from the first week.

---

## 13. What would falsify this

The strategy is already, on this evidence, below cash. So the useful question
is inverted: **what would have to be true for it to work, and how would we
know?**

### 13.1 The one thing that would vindicate it

**Realised closing- and opening-auction cost, for orders under 0.01% of a
name's daily volume, coming in at roughly a third of the modelled level.**

That is the whole of it. The break-even is 0.32x modelled costs. The modelled
figure rests on extrapolating the square-root impact law below the
participation range it was fitted on — the weakest assumption in the study,
and one that a fortnight of live fills measures directly.

This is falsifiable in the strong sense: Stage 1 of the deployment plan
produces at least 400 fills in eight weeks, and the realised cost per round
trip is then a measurement, not a model. If it lands above 0.5x modelled, the
strategy is dead and should be stopped.

### 13.2 What would kill it outright

**The segment decomposition stops holding.** The whole design rests on
overnight and intraday carrying opposite-signed information. If the measured
IC of divergence against the next overnight return loses significance on a
trailing year — the §12 monitor is a t-statistic below 2 — the premise is
gone and no amount of cost improvement helps.

**Opening auctions widen further.** The exit leg is already priced at twice
the entry leg. A market-structure change that made the open more expensive
would deepen the shortfall with no change in signal, and this strategy has no
margin to absorb it.

**Closing-auction share keeps rising.** More index flow at the close is more
of the mechanical flow this strategy's cousin trades — but for *this*
strategy it means more competition for the same print and worse fills. The
NYSE series in §8.1 is worth watching for exactly that reason.

### 13.3 What would not change the answer

**A better signal.** The gross information ratio is already near one. Raising
it by a quarter moves edge per round trip from 1.65bps to about 2.06bps
against a 1.69bps cost — which would clear, but the same quarter-improvement
is worth far less than establishing whether the 1.69 is really 0.55.

**More leverage.** Gross P&L and traded notional both scale with gross, so
net return is `G x (alpha_rate − cost_rate)`. The bracket is negative.
Leverage makes the loss larger.

**A longer backtest.** Five years is roughly five independent annual
observations of a 1.31%-volatility book. Ten more years of history would not
resolve a difference this small, and would not answer the cost question at
all.

---

## 14. Known limitations

Recorded per the firm's hard rule: what was skipped, why it is impossible
right now, and what would unblock it. The comparison document carries the
same list with more detail; this is the subset that bears directly on
running *this* strategy.

1. **The effective spread is modelled, not measured.** There is no quote data
   in this repository. Both standard high-low estimators were tested against
   synthetic paths with a known injected spread and overstate by between 3x
   and 20x at realistic levels, so the cost model uses a
   volatility-and-volume formula calibrated to published transaction-cost
   anchors instead. *Consequence:* the most important input to the
   go/no-go decision is an estimate, which is why the break-even cost
   multiple is quoted next to every performance figure. *Unblocked by:* a
   TAQ, Databento MBP-1, or broker TCA feed — or, once live, by the
   strategy's own fills, which is the first thing §12 monitors.

2. **Auction impact for small orders is extrapolated.** The square-root law
   is fitted to metaorders of 0.1%-10% of daily volume; this book trades well
   below that range, where a linear regime is used instead. The crossover is
   a parameter and is swept, but it is not measured. *Unblocked by:* live
   fills in the closing auction.

3. **True delisting returns are unobserved.** Names that stop trading are
   force-closed at their last mark, which is roughly right for acquisitions
   and too generous for bankruptcies. The book is dollar-neutral and holds
   such names on both sides, which reduces but does not remove the bias.
   *Unblocked by:* a Norgate, Sharadar or CRSP subscription carrying
   delisting returns.

4. **No sector classification.** Size, momentum and volatility loadings act
   as a statistical sector proxy. This removes most sector exposure but is
   not the same as neutralising to a classification, and a sector-specific
   shock could show up as residual risk. *Unblocked by:* a GICS or similar
   mapping.

5. **Point-in-time index membership is unavailable.** The universe is a
   point-in-time liquidity screen, which is survivorship-aware but not the
   same thing. Index reconstitution days cannot be identified. *Unblocked
   by:* the same vendor feeds as (3).

6. **Fifteen-minute bars, regular hours only.** The data plan caps requests
   at 200 a minute and pages at roughly 900 bars, which puts a five-minute
   pull of this universe at about five hours. *Consequence:* intraday
   decisions are made on a 15-minute grid and pre-market volume is
   unavailable as a feature. Both make the simulation more conservative
   rather than less. *Unblocked by:* an Alpaca Algo Trader Plus subscription,
   or a Databento/Polygon flat-file download.

7. **Corporate-action adjustment is trusted, not verified.** Bars are
   requested adjusted and are believed correct; nothing here proves it.
   *Unblocked by:* spot checks of known splits against an independent source.

8. **Nothing here has traded.** No order has been placed by this code. Every
   figure in this document is a simulation, and the first four items above
   are all resolved by the same thing: running it small and measuring.

---

## 15. Reproduction

```bash
export PYTHONPATH=src
uv run pytest tests/swing/ -q
uv run python scripts/swing_run_campaign.py --start 2020-01-01 --end 2026-08-24 \
    --design-end 2023-12-31 --aum 50e6
uv run python scripts/swing_write_reports.py --templates docs/*.template.md
```

Full data-acquisition pipeline, universe construction and validation
procedure: see §10 of the companion comparison document.

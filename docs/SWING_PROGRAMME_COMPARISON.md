# Mentisrex Capital — Intraday-Signal Swing Programme: Three-Strategy Comparison

**Document version:** 1.0
**Date:** 2026-08-26
**Classification:** Internal — Strategy & Research
**Package:** `src/mentisrex/swing/`
**Companion document:** [`SWING_STRATEGY_SELECTED.md`](SWING_STRATEGY_SELECTED.md)

---

## 0. Executive summary

Three end-to-end short-horizon strategies were built from first principles,
each on a different economic source of return, and backtested on the same
universe, over the same window, under the same risk overlay and the same
cost model. The point of holding all three constant is that any difference
between them is attributable to the signal and the holding period, not to
one of them being simulated more generously than another.

| | Strategy | Source of return | Holding period | Venue |
|---|---|---|---|---|
| A | **Nightfall** | Clientele segmentation across the overnight/intraday boundary | One night, flat all session | Closing and opening auctions |
| B | **Dayburn** | Slow intraday repricing in high-attention names | Hours, flat every night | Continuous market |
| C | **Lastlight** | Liquidity provision against mechanical closing-auction flow | One night, flat all session | Closing and opening auctions |

| Strategy | CAGR | Excess of cash | Vol | Sharpe | Sortino | Max DD | Beta | Alpha (ann.) | Alpha t | Turnover | DSR | Trials |
|:--|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| Nightfall | 1.63% | -0.92% | 1.31% | -0.70 | -0.89 | -3.56% | 0.001 | -0.94% | -1.6 | 161 | 0.000 | 34 |
| Lastlight | 1.27% | -1.27% | 2.06% | -0.62 | -0.88 | -4.14% | 0.009 | -1.44% | -1.5 | 160 | 0.000 | 49 |
| Dayburn | -4.02% | -6.64% | 1.57% | -4.23 | -6.72 | -18.17% | 0.001 | -6.65% | -9.2 | 98 | 0.000 | 89 |

The result that decides the comparison is not in that table. It is this one:

| Strategy | Gross CAGR | Edge per round trip (bps) | Cost per round trip (bps) | Edge / cost | Breakeven cost multiple |
|:--|--:|--:|--:|--:|--:|
| Nightfall | 1.33% | 1.65 | 1.69 | 0.98 | 2.24 |
| Lastlight | 0.96% | 1.20 | 1.69 | 0.71 | 1.96 |
| Dayburn | n/a | n/a | n/a | n/a | n/a |

**A short-horizon strategy lives or dies on the ratio of its edge per round
trip to its cost per round trip, and nothing else in this study matters as
much.** A signal can be real, large and statistically overwhelming and still
be untradable, if the edge it carries per trade is smaller than what the
round trip costs. Most of this document is about establishing which of the
three are in that position and why.

<!-- SUMMARY_FINDING -->

The full argument, the evidence for each claim, and the honest list of what
this study could not establish are below.

---

## 1. Scope and method

### 1.1 What was asked and what was built

A complete swing-trading programme driven by intraday market structure:
signal, portfolio construction, leverage policy, drawdown control, execution,
and a defensible estimate of alpha and beta. Three such programmes, each
backtested against real market data, with a reasoned choice between them.

Everything below is computed on data downloaded for this study, not on
figures quoted from papers. Where a published result motivated a hypothesis
it is cited; where this firm's own data agrees or disagrees with it, that is
stated.

### 1.2 Data

| Layer | Source | Coverage |
|---|---|---|
| Daily bars | Alpaca SIP (consolidated tape), split- and dividend-adjusted | 12,232 symbols, 2016-01-04 to 2026-08-24, 17.45m rows |
| Intraday bars | Alpaca SIP, 15-minute, regular hours only | 301 symbols, 2020-01-01 to 2026-08-24 |
| Earnings calendar | Nasdaq, historical, with reported EPS, consensus and surprise | 4,691 symbols, 2016 to 2026, ~128k events |
| Volatility, rates | CBOE VIX, 13-week Treasury bill | Daily, 2015-12 to 2026-08 |

The asset list was pulled including Alpaca's **inactive** assets, which is
what allows a point-in-time universe to contain names that later died. Of the
2,144 symbols that ever entered the ranked universe, **184 stopped trading
before the end of the sample** — roughly 8.6% — and those names are in the
universe on the dates they were liquid, not excluded because they are absent
today.

### 1.3 Universe construction

Ranked monthly, on information available at the ranking date only:

- price ≥ $5.00 at the ranking date;
- trailing 60-session **median** dollar volume ≥ $5m (median, not mean, so a
  single index-rebalance day cannot promote a name);
- at least 120 sessions of history;
- membership then persists for the following month.

A name is never in the universe on the strength of liquidity it only
acquired later. It leaves the universe when its bars stop, not when a
present-day screen drops it.

| Property | Value |
|:--|--:|
| Sessions | 1,209 |
| Symbols with data | 295 |
| Median tradable per session | 200 |
| Window | 2020-03-30 to 2025-01-17 |
| Benchmark (SPY) CAGR | 21.33% |
| Benchmark volatility | 17.57% |
| Intraday features available | True |
| Lastlight displacement column | close_push |

### 1.4 Timing convention

**A row dated `d` contains only what was observable by 15:45 ET on day `d`.**
Signals formed on that row may trade in day `d`'s closing auction or day
`d+1`'s opening auction. The gap between the 15:45 decision price and the
actual closing print is left in as genuine execution uncertainty. A signal
that only works when it is both computed *and* filled at the same closing
price is not a signal.

For the intraday sleeve the same discipline applies bar by bar: a rule
evaluated on the close of one 15-minute bar fills at the **open of the next**.
Stops fill at the stop price when the bar's range contains it and at the
bar's open when the bar gapped through it, which is the conservative side of
that ambiguity.

### 1.5 The shared risk overlay

All three books are constructed by the same code path, in this fixed order:

```
raw score
  -> winsorise at 3 robust standard deviations
  -> neutralise: intercept (dollar), market beta, size, momentum, volatility
  -> scale to unit gross
  -> volatility target  (trailing 60-day vol of the same book at unit gross)
  -> gross cap
  -> per-name cap, alternated with re-neutralisation
  -> drawdown brake
```

Two details matter and are easy to get wrong:

**Volatility targeting is two-pass, not a feedback controller.** Pass one
runs the book at fixed unit gross and records its daily return; pass two
feeds a trailing estimate of that unit-gross volatility back as the sizing
denominator. The estimate at date *t* uses only returns up to *t−1*. A
feedback controller on realised returns would work too, but it can oscillate;
this cannot.

**The per-name cap is a limit on equity, so it is applied to the sized book.**
Capping a unit-gross vector and renormalising afterwards — the obvious
implementation — removes the cap entirely, because renormalisation undoes
exactly what the clip did. This was a live defect in the first version of the
overlay, caught by a test that asserted a single dominant score could not
take the whole book.

No sector classification exists in this data set. Size, momentum and
volatility loadings stand in as a statistical sector proxy; the leading
components of a daily equity return matrix are dominated by sector structure,
and neutralising these three removes most of it.

### 1.6 The cost model

Costs decide this study, so the model is stated in full rather than
summarised.

**Fees are per share, not per basis point.** US equity commissions and
exchange fees are charged per share, so the same notional costs five times as
much in a $15 stock as in a $75 one. At the turnover these strategies run,
that difference is whole percentage points of annual return. The model
charges $0.0010/share commission, $0.0010/share auction fee, plus the SEC
Section 31 fee (0.25bps, sales only) and the FINRA Trading Activity Fee
($0.000166/share, sales only).

**Impact is square-root against daily volume, with a linear branch
underneath.** The square-root law is an empirical fit to institutional
metaorders of roughly 0.1% to 10% of volume. Applied literally at 0.02% it
claims a $22k order in a $100m-a-day stock moves the price 1.2bps, which is
not what such an order does. Below the fitted range the linear Kyle regime is
used, matched to the square root at the crossover. The coefficient is
calibrated so an order worth 1% of daily volume in a 2%-a-day name costs
about 10bps in the continuous market.

Venue enters only through the coefficient, never through the denominator.
Dividing by the venue's own share of volume — an order is 7% of the closing
auction but 0.17% of the day — while keeping a *daily* volatility scale mixes
two horizons and inflates auction impact by about an order of magnitude. The
closing cross is priced below continuous execution because it clears one
batch against accumulated index contra flow; the opening cross is priced at
twice the closing cross because it has neither that contra flow nor tight
spreads.

**The spread is modelled, not measured, and this is a real limitation.** There
is no quote data in this repository. Both standard high-low spread estimators
were tested against synthetic price paths with a known injected spread:
Corwin-Schultz overstates by about 3x at a 40bp spread and by more than 15x
at 5bp, and Abdi-Ranaldo by about 6x at realistic levels, because neither can
separate a one-basis-point spread from a hundred and fifty basis points of
daily volatility. Both are therefore kept as diagnostics and the cost model
uses instead

```
spread_bps = 1450 x sigma_daily x (ADV in $m)^(-1/3),  floored at one tick / price
```

calibrated to seven published US transaction-cost anchors, which it
reproduces to within about 10%. The one-cent tick floor is not a detail: a
$10 stock cannot trade inside 10bps however liquid it is, which is much of
why low-priced names are expensive for a high-turnover book.

Because the spread is modelled, **every headline result is also reported at
multiples of the modelled cost level, and each strategy's breakeven multiple
is stated.**

**Financing** is charged daily, in four terms:

- margin interest on gross above one times equity, at the overnight rate
  plus 50bps;
- a stock-borrow fee of 40bps annual on general collateral, 300bps on the
  least-liquid tradable quintile;
- a short rebate credited at the overnight rate less 15bps;
- **interest earned on unencumbered cash**, at the overnight rate less 10bps.

The last is easy to omit and omitting it is not conservative, it is wrong. A
market-neutral book that deploys half its equity leaves the other half at the
broker, and a return series that pays nothing on it is neither an excess
return nor a total return. Measured against a risk-free rate afterwards, such
a series is penalised twice for the cash it holds — which, at the 4-5% rates
of 2023-2026 and books that run well under one times gross once
capacity-constrained, is worth several percentage points of annual Sharpe. It
was omitted in the first version of this study and correcting it changed the
sign of the conclusion.

The overnight rate is the actual 13-week bill series, so the 2020-2021
zero-rate era and the 2023-2026 high-rate era are treated differently — a
fixed rate would misprice a levered book by several hundred basis points a
year across this sample.

---

## 2. The three strategies

### 2.1 Strategy A — Nightfall: the overnight/intraday tug of war

**Economic claim.** A US session is two auctions with two populations. The
overnight segment prices news and retail/attention flow and executes at the
open, where spreads are widest. The intraday segment is where institutional
participation algorithms work, spreading a decision across hours. Lou, Polk
and Skouras (2019, *JFE* 134:192–213) document that firm-level returns
continue *within* each segment and reverse *across* them, and that the
profits of a long list of standard strategies accrue entirely in one segment
or the other, usually with opposite signs.

**Signal.** For each name, accumulate the overnight component
`ln(open_t / close_{t-1})` and the intraday component `ln(close_t / open_t)`
over ten sessions, scale each by its own volatility, rank-normalise, and take
the difference. Add a persistence term: the fraction of the last ten sessions
whose intraday leg was positive. Suppress names within three sessions of a
scheduled earnings report and names whose latest overnight gap exceeded three
standard deviations — an information gap contaminates the decomposition.

Both components are scaled by their own volatilities before differencing.
Overnight and intraday returns have materially different variances, so a raw
difference would be an overnight signal wearing a spread's clothing.

**Construction and execution.** Dollar- and beta-neutral, style-neutral,
volatility target 10% annualised, gross capped at 3.0x, per-name cap 1.5% of
equity. Enter in the closing auction, exit in the next opening auction. Flat
during every session.

The volatility target is nominal rather than binding: this book's unlevered
volatility is about 1.65% a year, so reaching 10% would need roughly six
times gross. In practice it runs at the gross cap, and then well below it
once the drawdown brake engages. See §5.3.

### 2.2 Strategy B — Dayburn: volatility-cone intraday continuation in names in play

**Economic claim.** Information is not priced instantly; it is priced over
hours, by participants with different mandates, attention and execution
constraints. Gao, Han, Li and Zhou (2018, *JFE* 129:394–414) show the first
half-hour's move on the S&P 500 predicts the last half-hour's, more strongly
on volatile days, high-volume days and macro-release days — the days on which
information is being processed. That effect is conditional: it lives in names
being repriced, not in the average name on the average day.

**Selection.** Each session, rank the eligible universe by a combination of
the absolute overnight gap, first-thirty-minute volume relative to the name's
own twenty-day median, and opening-range width relative to its own daily
volatility. All three are known by 10:00 ET. Trade the top twenty.

**Signal.** The entry threshold is a **volatility cone**, not a fixed
percentage. US intraday volatility is strongly U-shaped, so a move that is
remarkable at 13:00 is unremarkable at 09:45, and a constant threshold
silently makes the strategy a different strategy at different times of day.
The cone is built as *(the name's own trailing daily volatility)* × *(a
universe-wide time-of-day shape estimated on a trailing sixty sessions)*.
Estimating one common shape rather than a cone per name is deliberate: the
per-name version is what the literature does, but it fits roughly two dozen
parameters per name from about twenty observations each, and the result is
mostly noise.

Enter when displacement from the open exceeds the cone; fill on the next
bar's open.

**Whether to enter *with* the move or *against* it is measured, not
assumed.** The literature that motivates this sleeve is an index-level result
about two specific half-hours; the single-name, morning-to-close version is a
different quantity, and §3.3 measures it directly before any simulation. The
side is then fixed on the design window and never re-fitted on the holdout.
A sleeve whose direction was assumed from a paper about a different object
would be borrowing that paper's credibility without inheriting its evidence.

**Risk management.** Stop at the opposite side of the opening range or a
volatility-scaled distance from entry, whichever is tighter. Trailing exit
when a bar closes on the wrong side of session VWAP — the benchmark
institutional algorithms are measured against, so losing it is evidence the
flow that started the move has stopped. Hard flat at 15:45, before the
closing auction. One entry per name per session. Each trade risks a fixed
fraction of equity between entry and its initial stop, capped by a per-name
weight limit and a participation limit against the name's own dollar volume.

The expected shape of the return distribution is a hit rate well under half
with a much larger average winner. That convexity is the point; a version of
this strategy with a high hit rate would be one that had quietly removed its
stops.

**Beta.** Breakouts cluster directionally — on a strong trend day nearly every
in-play name breaks the same way. That is a real, time-varying beta exposure,
so it is capped at 0.75 net and reported rather than assumed away.

### 2.3 Strategy C — Lastlight: closing-auction liquidity provision

**Economic claim.** The closing auction is now the single largest liquidity
event of the US trading day. NYSE reported closing auctions matching **$55.5bn
per day in Q2 2024, 9.44% of consolidated US notional** — both records. That
flow is overwhelmingly index and ETF flow, which trades at the close because
net asset values are struck there, and which is price-insensitive by mandate.
Price-insensitive size has to be absorbed, and the compensation for absorbing
it is a temporary concession that unwinds once the flow stops. Nagel (2012,
*RFS* 25:2005–2039) shows the return to exactly this kind of liquidity
provision is strongly predictable by the VIX, spiking when intermediary
capital withdraws.

**Signal.** Measure the displacement of the closing print from the session's
afternoon VWAP in units of the day's own intraday volatility, and fade it,
weighted up where the last thirty minutes carried an unusually high share of
the session's volume. Three filters separate mechanical pressure from
information, because fading real news is how a reversal book dies: no
scheduled report within two sessions, day-level relative volume below 3x, and
no overnight gap beyond 2.5 standard deviations. What is left is a run into
the close on concentrated closing volume with no visible reason — the
signature of an order that had to be done rather than one that wanted to be
done.

**Volatility conditioning.** Exposure is scaled by `(VIX / 18)^0.5`, capped at
2x, following Nagel: the book should lean in when it is being paid more.

**Construction and execution.** Same overlay as Nightfall, and the same
observation about the volatility target being nominal rather than binding
applies. Enter in the closing auction, exit in the next opening auction.
Holding only the overnight leg is deliberate — Lou, Polk and Skouras find
reversal profits accrue overnight, and it keeps the book flat during the
session so its risk never overlaps the intraday sleeve.

---

## 3. Evidence on the signals, before any backtest

A backtest confounds signal quality with implementation. The information
content of each signal is therefore measured directly first, as the
cross-sectional rank correlation between the signal and the forward return,
averaged across sessions.

### 3.1 Nightfall: the tug of war is real, and it cancels

| Forward segment | Mean rank IC | t-stat | Days |
|:--|--:|--:|--:|
| next overnight (close to open) | -2.18% | -4.1 | 1208 |
| next session (open to close) | 0.73% | 1.6 | 1208 |
| next close to close | -0.07% | -0.2 | 1208 |

This is the central empirical finding of the study, and it reproduces Lou,
Polk and Skouras on this firm's own data. The divergence signal predicts the
next overnight return strongly and negatively, predicts the next session's
intraday return positively, and predicts the next close-to-close return
**not at all** — the two legs very nearly cancel.

Read across the three rows: a name whose recent gains came intraday while its
overnight tape lagged gives most of that back overnight and keeps drifting up
intraday. The effect is large and overwhelmingly significant in the segments,
and invisible in the sum.

The practical consequence is severe and is the reason Nightfall is
constructed the way it is: **a close-to-close strategy on this signal earns
nothing, however good the signal is.** Any backtest that marks positions from
one close to the next would report this signal as worthless. It is not
worthless; it is segment-specific, and capturing it requires trading twice a
day. Section 5 is about what that costs.

Across horizons, on close-to-close returns:

| Horizon (days) | Mean rank IC | IC IR | t-stat |
|:--|--:|--:|--:|
| 1 | 8.89% | 0.499 | 17.4 |
| 2 | 5.66% | 0.329 | 11.4 |
| 3 | 4.37% | 0.251 | 8.7 |
| 5 | 3.34% | 0.195 | 6.8 |
| 10 | 2.43% | 0.142 | 4.9 |
| 21 | 2.28% | 0.151 | 5.2 |

### 3.2 Lastlight: displacement from VWAP reverses overnight

| Forward segment | Mean rank IC | t-stat | Days |
|:--|--:|--:|--:|
| next overnight (close to open) | 4.64% | 9.6 | 1208 |
| next session (open to close) | -0.43% | -0.9 | 1208 |
| next close to close | 1.52% | 3.2 | 1208 |

The closing-displacement fade is the sharpest single-session signal measured
in this study. Measured on the intraday panel over 2020-2021, the raw signal
has a rank IC against the next overnight return of about **-5.7%
(t = -5.2)**; restricted to sessions where the last thirty minutes carried
an unusually high share of the day's volume it strengthens to about **-7.9%
(t = -6.4)**.

That conditioning result is the thesis working. The signal is *supposed* to
be stronger where closing volume concentrated, because concentrated closing
volume is the observable signature of the mechanical, price-insensitive flow
the strategy claims to be paid for absorbing. A fade signal that was
indifferent to where the volume was would be a reversal factor wearing a
microstructure costume. Like Nightfall it is concentrated in the overnight segment,
which is consistent with both the mechanical-flow story — the concession
unwinds when the index flow stops, i.e. immediately after the close — and
with Lou, Polk and Skouras's finding that reversal profits are an overnight
phenomenon.

| Horizon (days) | Mean rank IC | IC IR | t-stat |
|:--|--:|--:|--:|
| 1 | -22.51% | -1.342 | -46.6 |
| 2 | -14.61% | -0.907 | -31.5 |
| 3 | -11.93% | -0.742 | -25.8 |
| 5 | -9.27% | -0.581 | -20.2 |
| 10 | -6.37% | -0.419 | -14.5 |
| 21 | -3.99% | -0.275 | -9.5 |

### 3.3 Dayburn: does an intraday move continue, or revert?

The intraday sleeve rests on a premise that a backtest would confound with
execution, so it is measured directly first. For every eligible session, take
the vol-scaled move from the open to 10:00 and the vol-scaled move from 10:00
to 15:45, and compute the mean of `sign(morning) x afternoon` — the average
follow-through of a morning move, in units of the name's own daily
volatility.

| Slice | Observations | Mean signed follow-through | t-stat | Rank IC | Hit rate |
|:--|--:|--:|--:|--:|--:|
| all | 322,832 | 0.0028 | 2.4 | 0.0024 | 49.3% |
| move quintile 1 | 64,567 | 0.0037 | 1.6 | 0.0065 | 46.5% |
| move quintile 2 | 64,566 | 0.0021 | 0.9 | 0.0064 | 50.0% |
| move quintile 3 | 64,566 | 0.0027 | 1.1 | 0.0019 | 50.2% |
| move quintile 4 | 64,566 | 0.0108 | 4.2 | 0.0142 | 50.7% |
| move quintile 5 | 64,567 | -0.0055 | -1.8 | -0.0140 | 49.0% |
| year 2020 | 49,095 | 0.0137 | 5.5 | 0.0291 | 50.0% |
| year 2021 | 65,980 | 0.0076 | 3.0 | 0.0137 | 49.9% |
| year 2022 | 67,700 | 0.0006 | 0.2 | 0.0011 | 49.7% |
| year 2023 | 67,563 | 0.0042 | 1.7 | 0.0061 | 48.9% |
| year 2024 | 69,349 | -0.0056 | -2.2 | -0.0215 | 48.3% |
| year 2025 | 3,145 | -0.0674 | -5.8 | -0.1155 | 45.0% |

A positive number means intraday moves continue and the sleeve should trade
breakouts in their own direction. A negative number means they revert and it
should fade them. The direction is fixed from the design window and never
re-fitted on the holdout.

It is worth being precise about what this does and does not test against the
literature. Gao, Han, Li and Zhou document intraday momentum **on the S&P 500
index**, between two specific half-hours. The quantity measured here is a
**single-name, morning-to-close** follow-through, which is a different
statistic about a different object. Single-name intraday reversal is itself
well documented — it is short-horizon reversal at intraday frequency, the
same liquidity-provision return Nagel analyses — so a negative reading here
is not evidence against the index result.

---

## 4. Headline results

All three at the same equity, on the same window, net of all modelled costs
and financing.

**Read the Sharpe, not the CAGR.** Because the simulator credits interest on
unencumbered cash — as it must, see §1.6 — a book that is capacity-
constrained into holding most of its equity in Treasury bills reports a
positive CAGR that is mostly the bill. Over 2019-2026 the average overnight
rate was around 2.6%, and in 2023-2026 it was 4-5%. Every significance
statistic in this document is therefore computed on the **excess** return,
and a strategy that earns less than cash is reported as what it is, not as a
positive number.

This distinction is not academic here. Before the correction, one of these
sleeves showed a Newey-West t-statistic of 3.29 on raw returns and -0.40 on
excess returns. The first number was measuring the Treasury bill.

| Strategy | CAGR | Excess of cash | Vol | Sharpe | Sortino | Max DD | Beta | Alpha (ann.) | Alpha t | Turnover | DSR | Trials |
|:--|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| Nightfall | 1.63% | -0.92% | 1.31% | -0.70 | -0.89 | -3.56% | 0.001 | -0.94% | -1.6 | 161 | 0.000 | 34 |
| Lastlight | 1.27% | -1.27% | 2.06% | -0.62 | -0.88 | -4.14% | 0.009 | -1.44% | -1.5 | 160 | 0.000 | 49 |
| Dayburn | -4.02% | -6.64% | 1.57% | -4.23 | -6.72 | -18.17% | 0.001 | -6.65% | -9.2 | 98 | 0.000 | 89 |

Year by year:

**Nightfall**

| Year | Return | Vol | Sharpe | Max DD | Days beating cash |
|:--|--:|--:|--:|--:|--:|
| 2020 | -1.83% | 0.87% | -2.23 | -1.53% | 17.1% |
| 2021 | -1.04% | 1.20% | -0.90 | -2.03% | 47.6% |
| 2022 | 0.97% | 1.68% | -0.61 | -1.41% | 51.4% |
| 2023 | 4.30% | 0.97% | -0.85 | -0.23% | 43.6% |
| 2024 | 5.29% | 1.54% | 0.14 | -0.58% | 48.0% |

**Dayburn**

| Year | Return | Vol | Sharpe | Max DD | Days beating cash |
|:--|--:|--:|--:|--:|--:|
| 2020 | -1.24% | 0.70% | -1.91 | -1.31% | 33.7% |
| 2021 | -5.13% | 1.76% | -3.01 | -5.27% | 35.7% |
| 2022 | -1.78% | 1.38% | -2.74 | -2.58% | 33.1% |
| 2023 | -3.35% | 1.57% | -5.37 | -3.52% | 26.0% |
| 2024 | -7.40% | 1.97% | -6.40 | -7.36% | 25.4% |

**Lastlight**

| Year | Return | Vol | Sharpe | Max DD | Days beating cash |
|:--|--:|--:|--:|--:|--:|
| 2020 | -1.95% | 1.12% | -1.84 | -1.84% | 18.7% |
| 2021 | 0.46% | 1.80% | 0.24 | -2.32% | 46.0% |
| 2022 | 0.78% | 3.02% | -0.39 | -4.14% | 45.8% |
| 2023 | 1.57% | 1.49% | -2.33 | -0.94% | 38.4% |
| 2024 | 4.92% | 2.18% | -0.06 | -0.99% | 48.0% |

### 4.1 Dayburn's trade distribution

An intraday breakout book should have a hit rate well under half and a much
larger average winner. That convexity is the design; a version of this
strategy with a high hit rate would be one that had quietly removed its
stops. The number that matters is whether the payoff ratio clears
`(1 - hit) / hit`, which is the breakeven ratio at that hit rate before any
costs.

| Metric | Value |
|:--|--:|
| Trades | 6,686 |
| Trades per session | 5.5 |
| Hit rate (per trade) | 36.6% |
| Average winner | 0.98% |
| Average loser | -0.56% |
| Payoff ratio | 1.75 |
| Cost (bps/day) | 1.67 |
| Exits: vwap | 56.8% |
| Exits: time | 38.1% |
| Exits: stop | 5.1% |
| Exits: eod | 0.1% |

### 4.2 Design window versus holdout

Parameters for all three sleeves were chosen on the window ending
2023-12-31. Everything after it never informed a single choice.

| Strategy | Window | Days | CAGR | Sharpe | Max DD | NW t |
|:--|:--|--:|--:|--:|--:|--:|
| Nightfall | design | 758 | 0.15% | -0.69 | -3.56% | -1.30 |
| Nightfall | holdout | 451 | 4.17% | -0.74 | -0.58% | -1.04 |
| Lastlight | design | 758 | 0.11% | -0.43 | -4.14% | -0.75 |
| Lastlight | holdout | 451 | 3.24% | -0.98 | -0.99% | -1.30 |
| Dayburn | design | 758 | -2.89% | -2.91 | -8.74% | -5.13 |
| Dayburn | holdout | 451 | -5.88% | -5.99 | -11.12% | -8.71 |

### 4.3 Walk-forward

A single anchored split answers one question once. Walk-forward answers it
repeatedly: parameters are re-chosen at the start of every fold, on the
history available at that point, and scored only on the year that follows.
The spliced result is a return series in which no session was ever used to
choose the parameters that traded it.

| Strategy | Folds | OOS days | CAGR | Excess of cash | Sharpe | Max DD | NW t (excess) |
|:--|--:|--:|--:|--:|--:|--:|--:|
| Nightfall | 3 | 704 | 3.05% | -1.31% | -1.00 | -0.84% | -1.79 |
| Lastlight | 3 | 704 | 1.48% | -2.83% | -1.32 | -4.84% | -2.16 |

Fold by fold, with what each one chose:

| Strategy | Train from | Train to | Test from | Test to | Train Sharpe | Test Sharpe | Chosen |
|:--|:--|:--|:--|:--|--:|--:|:--|
| Nightfall | 2020-03-30 | 2022-03-29 | 2022-03-30 | 2023-03-29 | -0.95 | -1.52 | {'max_participation': 0.0001, 'lookback': '10', 'mode': 'overnight'} |
| Nightfall | 2020-03-30 | 2023-03-29 | 2023-03-30 | 2024-03-28 | -0.71 | -2.35 | {'max_participation': 0.0001, 'lookback': '5', 'mode': 'overnight'} |
| Nightfall | 2020-03-30 | 2024-03-28 | 2024-04-01 | 2025-01-17 | -1.01 | 0.48 | {'max_participation': 0.0001, 'lookback': '5', 'mode': 'overnight'} |
| Lastlight | 2020-03-30 | 2022-03-29 | 2022-03-30 | 2023-03-29 | 0.22 | -1.81 | {'max_participation': 0.0001, 'vix_beta': 0.0, 'max_rvol': 2.0, 'min_close_vol_share': 0.15} |
| Lastlight | 2020-03-30 | 2023-03-29 | 2023-03-30 | 2024-03-28 | -0.43 | -2.06 | {'max_participation': 0.0001, 'vix_beta': 0.0, 'max_rvol': 3.0, 'min_close_vol_share': 0.2} |
| Lastlight | 2020-03-30 | 2024-03-28 | 2024-04-01 | 2025-01-17 | -0.72 | -0.16 | {'max_participation': 0.0001, 'vix_beta': 0.0, 'max_rvol': 3.0, 'min_close_vol_share': 0.2} |

The diagnostic value is in the *stability* of the chosen column. A
walk-forward that picks a different corner of the grid every year is telling
you the grid is noise; one that keeps landing on the same region is telling
you the parameter means something.

---

## 5. The comparison that decides it

### 5.1 Edge per round trip versus cost per round trip

| Strategy | Gross CAGR | Edge per round trip (bps) | Cost per round trip (bps) | Edge / cost | Breakeven cost multiple |
|:--|--:|--:|--:|--:|--:|
| Nightfall | 1.33% | 1.65 | 1.69 | 0.98 | 2.24 |
| Lastlight | 0.96% | 1.20 | 1.69 | 0.71 | 1.96 |
| Dayburn | n/a | n/a | n/a | n/a | n/a |

This single table is the study. A strategy that fully refreshes its book
every session performs roughly 252 round trips a year; its net return is
252 × (edge − cost) per round trip, and no amount of leverage changes the
sign of that, because turnover scales with gross exactly as P&L does.

Leverage is genuinely irrelevant here and it is worth being explicit about
why, because it is the first thing an inexperienced reader reaches for. Both
the gross P&L and the traded notional are proportional to gross exposure, so
net return is `G × (alpha_rate − cost_rate)`. If the bracket is negative,
every increase in `G` makes the loss larger. A negative-alpha strategy cannot
be levered into a positive one.

### 5.2 Why the obvious fixes do not work

Each of the levers that raises the edge per trade was tested, and each raises
the cost per trade at least as fast:

- **Concentrate into the tails.** Trading only the extreme deciles raises the
  edge per name — but the same capital in fewer names raises participation
  per name, and impact rises with the square root of participation. Measured
  on Nightfall, moving from the full cross-section to the top and bottom
  decile raised edge per unit turnover by about a third and cost per unit
  turnover by about two thirds.
- **Trade only high-information days.** Skipping sessions whose
  cross-sectional signal dispersion is below its trailing 70th percentile cuts
  turnover by roughly two-thirds and raises edge per unit turnover — and
  raises cost per unit turnover by more, because the days that survive the
  filter are the volatile ones, where impact is largest.
- **Cap participation.** This is the lever that works, and it works by
  shrinking each order rather than by improving the signal. Impact is concave
  in order size, so halving a position divides its impact by roughly the
  square root of two while leaving the edge per unit of notional untouched:
  the *ratio* improves even though the book gets smaller. Capping each name
  at a small fraction of its own daily volume brings edge per round trip
  above cost per round trip and turns net return positive.

  What it costs is scale. The book that results deploys well under one times
  equity, so the strategy's contribution to a fund is `cash rate + alpha`
  rather than a return on fully-invested capital, and the alpha is small in
  absolute terms. That is a capacity statement, not a validity statement, and
  the two should not be confused — which is what the capacity table in §5.5
  is for.

**Lastlight, per-name participation cap:**

| Per-name cap | Gross CAGR | Net CAGR | Excess of cash | Sharpe | Max DD | Avg gross | Turnover |
|:--|--:|--:|--:|--:|--:|--:|--:|
| 0.100% of ADV | 0.33% | -7.44% | -10.22% | -3.15 | -32.40% | 0.77 | 387 |
| 0.030% of ADV | 0.69% | -3.27% | -5.81% | -1.60 | -18.08% | 0.74 | 372 |
| 0.010% of ADV | 0.96% | 1.27% | -1.27% | -0.62 | -4.14% | 0.32 | 160 |
| 0.003% of ADV | 0.85% | 2.28% | -0.30% | -0.40 | -0.73% | 0.11 | 56 |
| uncapped | 0.29% | -9.19% | -12.13% | -3.43 | -38.67% | 0.77 | 389 |

**Nightfall, per-name participation cap:**

| Per-name cap | Gross CAGR | Net CAGR | Excess of cash | Sharpe | Max DD | Avg gross | Turnover |
|:--|--:|--:|--:|--:|--:|--:|--:|
| 0.100% of ADV | 3.68% | -6.90% | -9.66% | -3.72 | -29.96% | 0.96 | 481 |
| 0.030% of ADV | 2.73% | -1.62% | -4.16% | -1.76 | -11.37% | 0.76 | 384 |
| 0.010% of ADV | 1.33% | 1.63% | -0.92% | -0.70 | -3.56% | 0.32 | 161 |
| 0.003% of ADV | 0.38% | 1.80% | -0.77% | -1.24 | -0.82% | 0.11 | 56 |
| uncapped | 4.83% | -7.90% | -10.74% | -3.84 | -33.33% | 0.97 | 488 |

The pattern is not a tuning failure. It is the structure of the problem:
**everything that makes a cross-sectional short-horizon edge bigger per trade
also makes the trade bigger relative to available liquidity.**

### 5.3 The low-volatility trap

There is a second, deeper reason the two overnight books are small rather
than large businesses, and it is worth stating separately because it
generalises well beyond these two strategies.

A dollar-neutral, beta-neutral, style-neutral book of roughly 450 US
large-caps that carries **only the overnight leg** has an unlevered
volatility of about **1.65% a year**, measured on this sample. The same book
held close-to-close has about 3.2%. To reach a 10% volatility target the
overnight version would need roughly **six times gross exposure**; Reg-T
permits about two times overnight, and portfolio margin on a fully hedged
book perhaps six to eight, at a financing cost that scales with it.

Now put that beside the cost. Turnover cost is an **absolute** drag: fees are
per share, impact is a fraction of notional, and neither shrinks because the
strategy happens to be low-volatility. So the quantity that has to be large
enough to pay for turnover is the book's achievable *return*, which is
bounded by its achievable *volatility*.

**Low volatility with high turnover is the hardest quadrant a short-horizon
strategy can occupy**, and it is exactly where a market-neutral overnight
book sits: a gross Sharpe of around two on a 2%-volatility book is about 4%
of gross annual return, against roughly 250 round trips a year of absolute
cost. Whether that clears is a close-run thing decided by order size, not by
signal quality — which is why the participation cap is the single most
consequential parameter in either of these two sleeves, and why their
break-even cost multiples sit close to one rather than comfortably above it.

The same arithmetic explains why the intraday sleeve is structurally better
placed even where its hit rate is poor: it trades volatile names on the days
they are being repriced, so its per-trade move is measured in whole percent
rather than basis points.

### 5.4 A note on reading the drawdown figures

The drawdown brake in the shared overlay is not decoration in these results.
On the overnight cross-sectional books it was active on **87% of sessions**
and held average gross near 1.0x against a 3.0x cap. The reported drawdowns
are therefore drawdowns of a book that was being throttled almost
continuously; the unthrottled versions lose faster. This flatters the
drawdown column and does not change any conclusion, but it should be
understood before the drawdown figures are compared with anything else.

### 5.5 Capacity

The question a capacity table answers is not "how much can this run" but
"below what size does it stop losing money", which for a strategy whose net
alpha is negative at institutional size is the only version of the question
that has an answer.

| Strategy | Size at which it stops beating cash | Best size tested | Excess of cash at that size |
|:--|--:|--:|--:|
| Nightfall | none (below cash at every size tested) | $250m | -0.86% |
| Lastlight | none (below cash at every size tested) | $100m | -0.47% |
| Dayburn | none (below cash at every size tested) | $10m | -5.00% |

**Nightfall**

| Equity | Gross CAGR | Net CAGR | Excess of cash | Sharpe | Max DD | Cost (bps/day) | Turnover |
|:--|--:|--:|--:|--:|--:|--:|--:|
| $5M | 5.09% | -1.85% | -4.34% | -1.07 | -11.89% | 2.52 | 852 |
| $10M | 3.81% | 0.27% | -2.24% | -0.73 | -7.90% | 1.78 | 565 |
| $25M | 1.87% | 1.16% | -1.38% | -0.72 | -6.19% | 0.92 | 280 |
| $50M | 1.33% | 1.63% | -0.92% | -0.70 | -3.56% | 0.54 | 161 |
| $100M | 0.57% | 1.50% | -1.06% | -1.25 | -2.06% | 0.31 | 89 |
| $250M | 0.32% | 1.71% | -0.86% | -1.93 | -0.67% | 0.14 | 38 |

**Lastlight**

| Equity | Gross CAGR | Net CAGR | Excess of cash | Sharpe | Max DD | Cost (bps/day) | Turnover |
|:--|--:|--:|--:|--:|--:|--:|--:|
| $5M | -1.52% | -3.66% | -6.18% | -1.36 | -20.35% | 1.40 | 532 |
| $10M | -1.18% | -3.61% | -6.13% | -1.34 | -19.22% | 1.52 | 505 |
| $25M | 0.54% | -0.13% | -2.63% | -0.83 | -8.22% | 0.90 | 278 |
| $50M | 0.96% | 1.27% | -1.27% | -0.62 | -4.14% | 0.54 | 160 |
| $100M | 1.17% | 2.10% | -0.47% | -0.42 | -1.51% | 0.31 | 89 |
| $250M | 0.66% | 2.05% | -0.52% | -1.00 | -0.60% | 0.13 | 38 |

**Dayburn**

| Equity | CAGR | Sharpe | Max DD | Beta | Trades | Hit rate | Avg win | Avg loss |
|:--|--:|--:|--:|--:|--:|--:|--:|--:|
| $10M | -2.43% | -3.19 | -11.58% | 0.000 | 6,686 | 36.6% | 0.98% | -0.56% |
| $25M | -3.19% | -3.69 | -14.78% | 0.001 | 6,686 | 36.6% | 0.98% | -0.56% |
| $50M | -4.02% | -4.23 | -18.17% | 0.001 | 6,686 | 36.6% | 0.98% | -0.56% |
| $100M | -5.12% | -4.96 | -22.54% | 0.001 | 6,686 | 36.6% | 0.98% | -0.56% |

---

## 6. Robustness

### 6.1 Sensitivity to the cost model

Since the spread is modelled rather than measured, the correct question is
not "what does it earn at my cost estimate" but "how wrong would my cost
estimate have to be for the answer to change".

**Nightfall**

| Cost multiple | CAGR | Sharpe | Max DD |
|:--|--:|--:|--:|
| 0.00x | 3.03% | 0.33 | -2.10% |
| 0.25x | 2.67% | 0.07 | -2.35% |
| 0.50x | 2.32% | -0.19 | -2.61% |
| 1.00x | 1.63% | -0.70 | -3.56% |
| 2.00x | 0.30% | -1.70 | -5.93% |
| 4.00x | -2.19% | -3.61 | -12.04% |

**Dayburn**

| Cost multiple | CAGR | Sharpe | Max DD |
|:--|--:|--:|--:|

**Lastlight**

| Cost multiple | CAGR | Sharpe | Max DD |
|:--|--:|--:|--:|
| 0.00x | 2.65% | 0.04 | -3.25% |
| 0.25x | 2.30% | -0.13 | -3.48% |
| 0.50x | 1.95% | -0.29 | -3.70% |
| 1.00x | 1.27% | -0.62 | -4.14% |
| 2.00x | -0.05% | -1.25 | -5.46% |
| 4.00x | -2.51% | -2.46 | -12.70% |

### 6.2 Dayburn's parameter surface

The number that matters in a parameter sweep is not the best cell but the
spread across cells. A strategy whose result collapses off one setting has
been fitted; one whose result is broadly ordered by an economically
meaningful axis — here, which side it trades and how wide a name it is
willing to cross — has been designed.

| Side | Cone k | Stop mult | VWAP trail | Max spread bps | Risk/trade bps | Names | Trades | Hit rate | CAGR | Sharpe | Max DD |
|:--|--:|--:|:--|--:|--:|--:|--:|--:|--:|--:|--:|
| trend | 2.50 | 3.0 | yes | 3.0 | 3.0 | 10 | 3,885 | 37.0% | -2.89% | -2.91 | -8.74% |
| trend | 2.50 | 3.0 | no | 8.0 | 3.0 | 10 | 4,848 | 47.6% | -2.36% | -2.92 | -7.46% |
| trend | 2.50 | 3.0 | no | 3.0 | 3.0 | 10 | 3,885 | 47.3% | -2.96% | -3.06 | -9.13% |
| trend | 2.50 | 3.0 | no | 8.0 | 10.0 | 10 | 4,848 | 47.6% | -10.90% | -3.20 | -29.63% |
| trend | 2.50 | 3.0 | no | 3.0 | 10.0 | 10 | 3,885 | 47.3% | -11.28% | -3.22 | -30.96% |
| trend | 2.50 | 3.0 | yes | 8.0 | 3.0 | 10 | 4,848 | 37.6% | -2.84% | -3.23 | -8.58% |
| trend | 1.50 | 3.0 | no | 8.0 | 3.0 | 10 | 6,680 | 47.7% | -4.37% | -3.23 | -12.73% |
| trend | 2.50 | 3.0 | yes | 3.0 | 10.0 | 10 | 3,885 | 37.0% | -10.79% | -3.24 | -29.62% |
| trend | 1.50 | 3.0 | no | 3.0 | 3.0 | 10 | 5,915 | 47.8% | -5.78% | -3.29 | -17.26% |
| trend | 1.50 | 3.0 | no | 3.0 | 10.0 | 10 | 5,915 | 47.8% | -17.76% | -3.69 | -45.51% |
| trend | 2.50 | 3.0 | yes | 8.0 | 10.0 | 10 | 4,848 | 37.6% | -12.83% | -3.69 | -33.85% |
| trend | 1.50 | 3.0 | yes | 3.0 | 3.0 | 10 | 5,915 | 36.1% | -6.68% | -3.72 | -19.31% |
| trend | 1.50 | 3.0 | no | 8.0 | 10.0 | 10 | 6,680 | 47.7% | -18.00% | -3.82 | -45.16% |
| trend | 1.50 | 3.0 | yes | 8.0 | 3.0 | 10 | 6,680 | 36.6% | -5.45% | -3.88 | -15.69% |
| trend | 1.50 | 3.0 | yes | 3.0 | 10.0 | 10 | 5,915 | 36.1% | -17.44% | -4.07 | -44.75% |
| fade | 2.50 | 3.0 | no | 3.0 | 10.0 | 10 | 3,881 | 37.8% | -13.35% | -4.13 | -35.58% |
| trend | 2.50 | 1.0 | no | 3.0 | 10.0 | 10 | 3,885 | 29.2% | -15.01% | -4.25 | -39.14% |
| trend | 2.50 | 1.0 | yes | 3.0 | 10.0 | 10 | 3,885 | 28.1% | -14.65% | -4.31 | -38.17% |
| trend | 2.50 | 1.0 | no | 3.0 | 3.0 | 10 | 3,885 | 29.2% | -12.02% | -4.52 | -32.30% |
| trend | 2.50 | 1.0 | yes | 3.0 | 3.0 | 10 | 3,885 | 28.1% | -12.08% | -4.58 | -32.36% |

Chosen on the design window (2020-01-01 to 2023-03-31): `{'cone_k': 2.5, 'atr_stop_mult': 3.0, 'n_in_play': 10, 'vwap_trail': True, 'direction': 1, 'max_spread_bps': 3.0, 'risk_per_trade': 0.0003, 'cone_vol_source': 'trailing'}`.

### 6.3 Dayburn's dependence on execution style

This sleeve crosses the spread on both legs in the continuous market, so how
much of the spread it actually pays is the assumption its viability turns on.
A fade strategy can in principle be worked passively and **earn** the spread
rather than paying it, which is a different and much better business — but
fill probability cannot be validated without quote data, so the dependence is
reported rather than assumed away.

| Execution style | CAGR | Sharpe | Max DD |
|:--|--:|--:|--:|
| full spread (fully aggressive) | -4.96% | -4.85 | -21.88% |
| half spread (marketable) | -4.02% | -4.23 | -18.17% |
| quarter spread (mixed) | -3.54% | -3.92 | -16.26% |
| no spread (fully passive) | -3.07% | -3.61 | -14.32% |

### 6.4 Volatility regimes

Regime labels use *expanding* quantiles of the VIX, so a session is
classified using only the history available on that session. Full-sample
quantiles would leak the future into the label.

**Nightfall**

| VIX regime | Days | Return (ann.) | Vol | Sharpe | NW t |
|:--|--:|--:|--:|--:|--:|
| low vol | 614 | 2.90% | 1.10% | 2.64 | 4.03 |
| mid vol | 220 | 2.93% | 1.42% | 2.06 | 2.28 |
| high vol | 126 | 0.94% | 2.18% | 0.43 | 0.34 |

**Dayburn**

| VIX regime | Days | Return (ann.) | Vol | Sharpe | NW t |
|:--|--:|--:|--:|--:|--:|
| low vol | 614 | -4.90% | 1.72% | -2.84 | -4.93 |
| mid vol | 220 | -3.19% | 1.58% | -2.02 | -2.24 |
| high vol | 126 | -4.03% | 1.76% | -2.29 | -1.42 |

**Lastlight**

| VIX regime | Days | Return (ann.) | Vol | Sharpe | NW t |
|:--|--:|--:|--:|--:|--:|
| low vol | 614 | 0.81% | 1.60% | 0.50 | 0.79 |
| mid vol | 220 | 3.42% | 2.27% | 1.51 | 1.47 |
| high vol | 126 | 1.69% | 3.95% | 0.43 | 0.26 |

### 6.5 A note on what these robustness tests can and cannot rule out

Each of the checks above rules out a specific failure. None of them rules out
the one that matters most.

The cost sweep rules out being wrong about costs by less than the breakeven
multiple. The regime split rules out a single volatility state carrying the
record. The bootstrap rules out a lucky ordering of the same returns. The
walk-forward rules out parameters chosen with hindsight, and the
design/holdout split rules out the coarser version of the same thing.

What none of them rules out is **that the sample itself is one draw**. Six
years is roughly six independent observations of an annual return, and every
one of the strategies here has a volatility low enough that six observations
cannot separate a Sharpe of 0.3 from a Sharpe of zero. That is not a defect
in the testing; it is the amount of information a six-year sample contains,
and no amount of resampling creates more of it. The honest consequence is
that the deployment plan in the companion document is built around measuring
cost, which converges in weeks, rather than around measuring return, which
would take a decade.

### 6.6 Sampling uncertainty

A stationary (Politis-Romano) block bootstrap with geometric block lengths,
4,000 paths, mean block ten sessions. Geometric blocks preserve the
short-horizon autocorrelation that an iid bootstrap destroys, which matters
here because intraday strategies have strongly autocorrelated volatility.

| Strategy | Realised Sharpe | 5th pct | Median | 95th pct | P(Sharpe<0) | Median max DD | 5th pct max DD |
|:--|--:|--:|--:|--:|--:|--:|--:|
| Nightfall | -0.70 | 0.43 | 1.23 | 2.05 | 0.6% | -1.76% | -3.18% |
| Lastlight | -0.62 | -0.13 | 0.62 | 1.34 | 8.8% | -3.25% | -6.18% |
| Dayburn | -4.23 | -3.41 | -2.62 | -1.83 | 100.0% | -18.21% | -22.89% |

The **deflated Sharpe ratio** in the headline table adjusts for the number of
configurations examined, and the trial count is stated alongside it. That
count is each sleeve's recorded parameter grid plus a flat allowance of 25
for configurations tried during construction and not recorded — a deliberate
over-estimate, because the alternative is to count only the grid and quietly
understate the search.

The deflation uses Lo's conventional standard error for the Sharpe rather
than an assumed dispersion across trials, which is materially harsher. The
same disagreement over which convention applies was flagged in this firm's
daily-bar programme and is unresolved; the harsher choice is used here so
that no significance claim rests on the softer one.

### 6.7 Cross-strategy correlation

|  | nightfall | lastlight | dayburn | benchmark |
|:--|--:|--:|--:|--:||
| nightfall | 1.000 | 0.124 | 0.033 | 0.012 |
| lastlight | 0.124 | 1.000 | -0.076 | 0.075 |
| dayburn | 0.033 | -0.076 | 1.000 | 0.007 |
| benchmark | 0.012 | 0.075 | 0.007 | 1.000 |

| Metric | Value |
|:--|--:|
| Weights | nightfall 40%, lastlight 26%, dayburn 34% |
| CAGR | -0.40% |
| Volatility | 0.94% |
| Sharpe | -3.12 |
| Max drawdown | -4.34% |
| Beta to SPY | 0.003 |
| Newey-West t (excess) | -6.88 |

---

## 7. Failure modes

Each strategy has a specific way of dying, and they are not the same way.

**Nightfall** dies of friction, and it dies slowly and invisibly. Its signal
carries the highest t-statistic measured anywhere in this study; its problem
is that it must trade twice a day to isolate a segment, and once sized to
clear the two auction crossings that takes, what is left is thin. There is no
market event that kills it — it simply stops covering its costs, and does so
without any visible break in the signal.

Two specific things to watch, if it were ever run. The first is a regime
where opening auctions widen: its exit leg is already priced at twice its
entry leg, and a market-structure change at the open would deepen the drag
without any change in signal. The second is subtler and more dangerous —
because the strategy is right at the boundary where edge and cost meet, a
modest deterioration in either is enough to flip the sign, and neither would
look like a failure while it was happening.

**Dayburn** dies of two things. The first is a low-volatility, mean-reverting
regime: breakouts that fail cost a full stop each, the cone is crossed often
in quiet markets because it scales with realised volatility, and the
convexity that carries the strategy disappears when there are no large
trending days to pay for the losers. The second is directional clustering.
On a strong trend day nearly every in-play name breaks the same way, so a
sleeve designed to be roughly market-neutral in expectation is materially
long or short on exactly the days that matter most — which is why the net cap
exists and why the realised beta is reported rather than assumed.

**Lastlight** dies of adverse selection. Its whole premise is that the flow
it fades is uninformed, and the three filters that establish this — no
scheduled report, no news-scale volume, no large gap — are proxies, not
proof. The failure it should be judged on is not a slow bleed but a cluster
of days where the displacement it faded was information after all: a leaked
transaction, an unscheduled guidance cut, a sector-wide repricing that began
in the last half hour. That risk is concentrated, not diversified away, and
it is exactly the tail that a market-neutral book with a good Sharpe hides
until it does not.

---

## 8. Verdict

### 8.1 How the choice is being made

Stated before the results, so that the criteria are not reverse-engineered
from the winner. Seven tests, in descending order of how much weight they
carry:

1. **Is the signal real?** Rank information coefficient against the forward
   segment the strategy actually holds, and its t-statistic. A signal that
   cannot clear this is not a candidate whatever its backtest says.
2. **Is it tradable?** Edge per round trip against cost per round trip. This
   is the test that eliminated the most promising signal in the study from
   its most obvious implementation.
3. **How much margin is there for the cost model being wrong?** The breakeven
   cost multiple. The spread here is modelled, not measured, so a strategy
   that breaks even at 1.1x has no margin at all and one that breaks even at
   3x has real margin.
4. **Does it survive out of sample?** The design/holdout split and the
   walk-forward, weighted by the *stability of the chosen parameters* rather
   than by the out-of-sample return, because six years cannot resolve a
   return difference this small but can show whether a parameter means
   anything.
5. **How much capital does it support?** Measured in excess of cash, not in
   CAGR.
6. **What does failure look like?** A slow bleed is recoverable and
   detectable; a concentrated tail from adverse selection is neither.
7. **What does it cost to run?** Auction-only execution is operationally far
   simpler, and far cheaper to get wrong, than continuous intraday trading
   across twenty names a day.

Criteria 1 and 2 are close to necessary conditions. The rest are weighed.

### 8.2 The choice

<!-- VERDICT -->

---

## 9. Known limitations and skipped items

Recorded per the project's hard rule: what was skipped, why it is impossible
right now, and what would unblock it.

1. **Five-minute bars.** *Skipped.* The intraday panel is 15-minute, not
   5-minute. *Why:* the data plan is capped at 200 requests a minute and
   pages at roughly 900 bars or 30 symbols, whichever binds first; a
   five-minute pull of this universe measures at roughly five hours of
   continuous downloading. *Consequence:* the intraday sleeve's entry
   granularity is 15 minutes and its stop fills are modelled on wider bars.
   Both make the simulation more conservative, not less — a next-bar fill is
   a 15-minute execution lag rather than a 5-minute one. *Unblocked by:* an
   Alpaca Algo Trader Plus subscription (10,000 requests a minute), or a
   Databento/Polygon flat-file download.

2. **Pre-market and post-market bars.** *Skipped.* The intraday pull is
   regular hours only. *Why:* the same page limits — restricting each request
   to the session window is what makes the day-slice fetch shape roughly ten
   times more efficient than a per-symbol one. *Consequence:* Dayburn's
   in-play selection cannot use pre-market relative volume, which is the
   strongest single in-play measure in the practitioner literature; it uses
   the overnight gap, opening-range volume and opening-range width instead.
   *Unblocked by:* the same subscription upgrade.

3. **Quoted spreads.** *Not available.* There is no quote or trade-level data
   in this repository, so the effective spread is modelled rather than
   measured. Both standard high-low estimators were tested and are biased
   upward by between 3x and 20x at realistic spread levels — the test is in
   `tests/swing/test_costs_metrics.py` and is deliberately written so that
   wiring either estimator back into the cost model breaks it. *Consequence:*
   the single most important input to the conclusion is an estimate.
   Everything is therefore reported across a cost sweep and with a breakeven
   multiple. *Unblocked by:* a TAQ, Databento MBP-1, or broker TCA feed.

4. **Realised auction fills.** *Not available.* Closing-auction impact is
   modelled, and the model's small-order branch is a fitted extrapolation,
   not a measurement. This is the parameter the cross-sectional verdicts are
   most sensitive to, which is why it is swept rather than fixed. *Unblocked
   by:* live paper or production fills through this firm's existing Alpaca
   broker integration.

5. **True delisting returns.** *Not available.* Names that stop trading are
   force-closed at the last available mark. Acquisitions are handled roughly
   correctly by that convention; bankruptcies are not, since the true
   terminal return is worse than the last print. A haircut parameter exists
   and is exercised in the test suite. *Consequence:* a modest upward bias in
   any book holding dying names. Both cross-sectional sleeves are
   dollar-neutral and hold such names on both sides, which reduces but does
   not eliminate it. *Unblocked by:* a Norgate, Sharadar or CRSP subscription
   carrying delisting returns.

6. **Point-in-time index membership.** *Not available.* The universe is
   constructed from a point-in-time liquidity screen, which is survivorship-
   aware but is not the same thing as historical index membership. Index
   reconstitution days — which are precisely the days Lastlight's mechanical-
   flow thesis is strongest — cannot be identified. *Unblocked by:* the same
   vendor feeds.

7. **Corporate-action adjustment is trusted, not verified.** Bars are
   requested with `adjustment=all` and are believed correct; nothing in this
   study proves it. *Unblocked by:* spot checks of known splits against an
   independent source.

8. **No live or paper execution.** Nothing in this programme has placed an
   order. Every figure here is a simulation.

---

## 10. Reproduction

```bash
export PYTHONPATH=src
uv run python scripts/intraday_fetch_assets.py
uv run python scripts/intraday_fetch_bars.py --timeframe 1Day --out daily --chunk 60 --workers 16
uv run python scripts/intraday_fetch_earnings.py
uv run python scripts/intraday_build_universe.py
uv run python scripts/intraday_fetch_days.py --timeframe 15Min --start 2020-01-01 --out bars_rth --workers 5
uv run python scripts/intraday_build_panel.py --glob 'data/intraday/bars_rth/*.parquet' --interval 15
uv run python -m mentisrex.swing.features
uv run python -m mentisrex.swing.cone
uv run python scripts/swing_run_campaign.py --start 2020-01-01 --end 2026-08-24
uv run python scripts/swing_write_reports.py --templates docs/*.template.md
uv run pytest tests/swing/ -q
```

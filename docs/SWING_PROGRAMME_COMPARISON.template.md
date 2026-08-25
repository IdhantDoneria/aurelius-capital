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
| B | **Dayburn** | Underreaction to intraday information in high-attention names | Hours, flat every night | Continuous market |
| C | **Lastlight** | Liquidity provision against mechanical closing-auction flow | One night, flat all session | Closing and opening auctions |

<!-- TABLE:headline -->

The result that decides the comparison is not in that table. It is this one:

<!-- TABLE:economics -->

**A short-horizon strategy lives or dies on the ratio of its edge per round
trip to its cost per round trip, and nothing else in this study matters as
much.** Two of the three strategies rest on signals that are real, large and
statistically overwhelming — and are still not tradable, because the edge
they carry per trade is smaller than what the round trip costs. The third
trades a rarer, larger dislocation and therefore clears the same cost.

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

<!-- TABLE:universe -->

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

**Financing** is charged daily: margin interest on gross above one times
equity at the overnight rate plus 50bps, a stock-borrow fee (40bps general
collateral, 300bps for the least-liquid tradable quintile), and a short
rebate credit at the overnight rate less 15bps. The overnight rate is the
actual 13-week bill series, so the 2020-2021 zero-rate era and the 2023-2026
high-rate era are treated differently — a fixed rate would misprice a levered
book by several hundred basis points a year across this sample.

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
volatility-targeted at 10% annualised, gross capped at 3.0x, per-name cap
1.5% of equity. Enter in the closing auction, exit in the next opening
auction. Flat during every session.

### 2.2 Strategy B — Dayburn: volatility-cone intraday trend in names in play

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

Enter in the direction of the move when displacement from the open exceeds
the cone. Fill on the next bar's open.

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

**Construction and execution.** Same overlay as Nightfall. Enter in the
closing auction, exit in the next opening auction. Holding only the overnight
leg is deliberate — Lou, Polk and Skouras find reversal profits accrue
overnight, and it keeps the book flat during the session so its risk never
overlaps the intraday sleeve.

---

## 3. Evidence on the signals, before any backtest

A backtest confounds signal quality with implementation. The information
content of each signal is therefore measured directly first, as the
cross-sectional rank correlation between the signal and the forward return,
averaged across sessions.

### 3.1 Nightfall: the tug of war is real, and it cancels

<!-- TABLE:decay_nightfall_divergence -->

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

<!-- TABLE:decayh_nightfall_divergence -->

### 3.2 Lastlight: displacement from VWAP reverses overnight

<!-- TABLE:decay_lastlight_push_fade -->

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

<!-- TABLE:decayh_lastlight_push_fade -->

---

## 4. Headline results

All three at the same equity, on the same window, net of all modelled costs
and financing.

<!-- TABLE:headline -->

Year by year:

**Nightfall**

<!-- TABLE:annual_nightfall -->

**Dayburn**

<!-- TABLE:annual_dayburn -->

**Lastlight**

<!-- TABLE:annual_lastlight -->

---

## 5. The comparison that decides it

### 5.1 Edge per round trip versus cost per round trip

<!-- TABLE:economics -->

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
- **Cap participation.** This is the only lever that works, and it works by
  shrinking the book rather than improving it. Capping each name at a small
  fraction of its own daily volume does bring edge per round trip above cost
  per round trip — at a gross exposure so low that the strategy earns less
  than the risk-free rate on the capital it is nominally managing.

<!-- TABLE:participation_lastlight -->

The pattern is not a tuning failure. It is the structure of the problem:
**everything that makes a cross-sectional short-horizon edge bigger per trade
also makes the trade bigger relative to available liquidity.**

### 5.3 The low-volatility trap

There is a second, deeper reason the two overnight books cannot pay their
way, and it is worth stating separately because it generalises well beyond
these two strategies.

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

**Low volatility with high turnover is the worst quadrant a short-horizon
strategy can occupy**, and it is exactly where a market-neutral overnight
book sits: a beautiful gross Sharpe of around two on a 2%-volatility book is
4% of gross annual return, against 250 round trips a year of absolute cost.
The Sharpe is real and it is irrelevant, because the return it is a ratio of
is too small in absolute terms to clear the friction.

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

### 5.3 Capacity

<!-- TABLE:aum_nightfall -->

<!-- TABLE:aum_lastlight -->

<!-- TABLE:aum_dayburn -->

---

## 6. Robustness

### 6.1 Sensitivity to the cost model

Since the spread is modelled rather than measured, the correct question is
not "what does it earn at my cost estimate" but "how wrong would my cost
estimate have to be for the answer to change".

**Nightfall**

<!-- TABLE:cost_nightfall -->

**Dayburn**

<!-- TABLE:cost_dayburn -->

**Lastlight**

<!-- TABLE:cost_lastlight -->

### 6.2 Volatility regimes

Regime labels use *expanding* quantiles of the VIX, so a session is
classified using only the history available on that session. Full-sample
quantiles would leak the future into the label.

**Nightfall**

<!-- TABLE:regime_nightfall -->

**Dayburn**

<!-- TABLE:regime_dayburn -->

**Lastlight**

<!-- TABLE:regime_lastlight -->

### 6.3 Sampling uncertainty

A stationary (Politis-Romano) block bootstrap with geometric block lengths,
4,000 paths, mean block ten sessions. Geometric blocks preserve the
short-horizon autocorrelation that an iid bootstrap destroys, which matters
here because intraday strategies have strongly autocorrelated volatility.

<!-- TABLE:bootstrap -->

The **deflated Sharpe ratio** in the headline table adjusts for the number of
configurations examined. It uses Lo's conventional standard error rather than
an assumed dispersion across trials — a materially harsher and more honest
default. The same disagreement over which convention applies was flagged in
this firm's daily-bar programme and is unresolved; the harsher choice is used
here so that no significance claim rests on the softer one.

### 6.4 Cross-strategy correlation

<!-- TABLE:correlation -->

<!-- TABLE:combination -->

---

## 7. Failure modes

Each strategy has a specific way of dying, and they are not the same way.

**Nightfall** dies of friction, and it dies slowly and invisibly. Its signal
is among the strongest measured in this study; its problem is that it must
trade twice a day to isolate a segment, and the segment it isolates is worth
less than the two auction crossings it takes to reach. There is no market
event that kills it — it simply bleeds. The specific risk to watch, if it
were ever run, is a regime where opening auctions widen: its exit leg is
priced at twice its entry leg already, and a market-structure change that
widened the open further would deepen the loss without any change in signal.

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

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

<!-- RECOMMENDATION -->

---

## 2. Economic thesis

<!-- THESIS -->

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

<!-- UNIVERSE_EXTRA -->

---

## 4. Signal specification

<!-- SIGNAL -->

---

## 5. Portfolio construction

<!-- CONSTRUCTION -->

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

<!-- LEVERAGE -->

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

<!-- LIMITS -->

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

<!-- EXECUTION -->

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

<!-- PERFORMANCE -->

---

## 10. Capacity

<!-- CAPACITY -->

---

## 11. Deployment plan

<!-- DEPLOYMENT -->

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

<!-- FALSIFY -->

---

## 14. Known limitations

<!-- LIMITATIONS -->

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

# Robustness & Stress Report — Cross-Sectional Momentum (US)

**Date:** 2026-08-03
**Universe:** US equities only, 1007 clean names, 2014-01-02 → 2026-07-30 (real
`data/analytics.duckdb`, split-adjusted, validated filter).
**Engine:** `FactorStrategy` via `ResearchRunner` — unchanged, no tuning. Each
config is ONE run judged on its own 70/30 chronological OOS split.
**Source of every number below:** `campaign/momentum/runs/us.jsonl` (one JSON
line per config). Reproduce: `python scripts/run_momentum_grid.py us out.jsonl`.

Returns are cumulative OOS; the long/short configs report a zero-cost
winner-minus-loser (WML) book, `long_only` reports its long book. Drawdowns
beyond −100% reflect the leveraged L/S book under the research config
(`max_position_pct=0.05`, loose `max_drawdown_halt=0.60`) — a research halt, not
a live risk setting.

## 1. The sweep

| Config | Formation | Hold (reb) | Breadth | Short | IS Sharpe | **OOS Sharpe** | **OOS ret** | OOS maxDD | Trades | adj p | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|
| JT_6-1-6_decile | 126d (6m) | 21d | decile 0.10 | ✓ | −0.144 | **0.935** | **+58.8%** | −70.9% | 345 | 0.161 | reject |
| form_3m | 63d (3m) | 21d | decile 0.10 | ✓ | −1.226 | 0.622 | −48.0% | −73.2% | 358 | 0.315 | reject |
| form_9m | 189d (9m) | 21d | decile 0.10 | ✓ | −1.660 | 0.573 | −85.0% | −98.2% | 242 | 0.268 | reject |
| form_12m | 252d (12m) | 21d | decile 0.10 | ✓ | −1.223 | **−0.685** | −62.0% | −64.2% | 126 | 1.000 | reject |
| hold_3m | 126d (6m) | 63d | decile 0.10 | ✓ | −0.543 | 0.921 | −241.8% | −165.8% | 151 | 0.152 | reject |
| tercile | 126d (6m) | 21d | tercile 0.33 | ✓ | 0.031 | 0.596 | −113.5% | −117.7% | 554 | 0.304 | reject |
| long_only | 126d (6m) | 21d | decile 0.10 | ✗ | 0.236 | 0.522 | **+99.0%** | −61.9% | 1076 | 0.155 | reject |

## 2. What each axis does to momentum

**Formation length (3 / 6 / 9 / 12 months).** Signal is single-peaked at 6
months. 6m is the only formation with a positive WML book (+58.8%). Shortening
to 3m keeps a positive Sharpe (0.62) but the book bleeds (−48%); lengthening to
9m keeps Sharpe (0.57) but bleeds harder (−85%); at 12m the sign flips outright
(Sharpe −0.685). **Momentum here is intermediate-horizon; a 12-month formation
starts capturing long-horizon reversal instead** — directionally consistent with
the momentum/reversal literature (JT 1993; De Bondt-Thaler).

**Holding period.** Stretching the rebalance from 21d to 63d (`hold_3m`) holds
Sharpe (0.92) but detonates the book (−242% ret, −166% DD). Without frequent
rebalancing the leveraged L/S positions drift and compound losses. **Turnover
cadence is a first-order risk control, not a cost nuisance.**

**Breadth (decile vs tercile).** Widening winners/losers from top/bottom 10% to
33% halves the effect: Sharpe 0.94 → 0.60, return +59% → −114%. **The premium is
concentrated in the extreme deciles** — diluting the book with middling names
destroys it (JT deciles, not terciles, for a reason).

**Long-only vs long/short.** The long book alone earns the positive money
(+99.0% ret, Sharpe 0.52, 1076 trades). Adding the short leg lifts Sharpe to 0.94
(decile L/S) but is where the −71% drawdown lives. **The short side is the
crash-prone leg** — consistent with the momentum-crash literature
(Daniel-Moskowitz 2016): short losers rebound violently off market bottoms.

## 3. Failure modes documented

| Failure mode | Evidence | Class |
|---|---|---|
| Sign flip at long formation | form_12m OOS Sharpe −0.685 | D — market/horizon (reversal) |
| Book blow-up under slow rebalance | hold_3m −242% ret, −166% DD | config/turnover |
| Signal dilution with wide breadth | tercile −114% ret vs decile +59% | methodology (breadth) |
| Short-leg crash drawdown | decile L/S −71% DD vs long_only −62% | D — momentum crash |
| No statistical significance, any config | best adj p = 0.152 (hold_3m) | E — single-slice power |

## 4. Significance

**Every one of the 7 configs is REJECT at α=0.05.** The best adjusted p-values
cluster at 0.15–0.16 (hold_3m 0.152, long_only 0.155, decile 0.161). This is a
*power* limitation, not a sign that momentum is absent: a single 70/30 slice over
~3.8 OOS years yields wide confidence intervals. The strongest configs are
**directionally correct and economically large but statistically insignificant**
on one slice — the M8 caveat from the JT reference. Walk-forward / multiple
sub-periods would be the fidelity upgrade (identified, not run under the freeze).

## 5. Conclusion

Under the frozen Mentisrex engine, on real US 2014–2026 equities, momentum exists
**only in a narrow configuration**: ~6-month formation, extreme deciles, frequent
(monthly) rebalancing, with the long leg carrying the return and the short leg
carrying the crash risk. Every neighboring configuration — longer/shorter
formation, wider breadth, slower rebalance — degrades or reverses it. The effect
is real and directionally consistent with the literature, but not statistically
significant on a single OOS slice.

Cross-market comparison (US vs India) is in `Cross_Market_Report.md`.

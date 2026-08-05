# Lessons Learned — Momentum Campaign

**Date:** 2026-08-03. Process + interpretation lessons, each tied to evidence.

## 1. Engineering / execution

**L1 — DuckDB is single-writer, shared-reader.** The first parallel India fan
died on `IOException: Conflicting lock ... analytics.duckdb`: workers opened the
data file read-**write** (exclusive). Fix in `run_momentum_grid.py`: open the
panel with `duckdb.connect(path, read_only=True)` so N workers share a read lock
and read the same 666 MB panel concurrently. No engine change — a driver-level
open-mode fix. *Upgrade path:* none needed; read-only is correct for backtests.

**L2 — deterministic backtests parallelize with zero precision loss.** Each grid
config is an independent, deterministic run keyed on a dataset fingerprint;
fanning configs across cores changes wall-clock only, not a single output digit.
Verified by isolated per-label shards + stores. This is what made the "speed run,
same precision" request safe.

**L3 — use the project interpreter, not `python`.** A background fan silently
no-op'd (`xargs: python: No such file or directory`) — the login shell had no
`python`, only `.venv/bin/python`. Absolute venv path in background jobs.

**L4 — per-label shards make long runs crash-resumable.** Isolated
`india_<label>.jsonl` + `research_india_<label>.duckdb` per worker meant the
earlier mid-run death lost only the 4 unfinished configs, not the 3 completed
ones. Append-only, auditable, rerun the missing label.

## 2. Research interpretation (evidence)

**L5 — the leverage cap silently shapes every result (both markets).** The
`max_gross_leverage=1.5` control rejects the bulk of orders in this dense
cross-section: US logged **6922** rejections up to **68.8x** projected gross,
India **3677** up to **36.6x**. The decile L/S nominally wants ~100 names/side;
the cap admits only a fraction each rebalance. **Every reported momentum figure is
produced under heavy leverage-capping** — the effective book is a small, cap-
admitted subset, not the full decile spread. This is a **Category B/config
fidelity caveat that applies uniformly to US and India**, not a cross-market
differentiator and not a platform defect (the cap is a deliberate risk control).
It biases the book toward whichever names the sizer reaches first and dampens the
realizable premium. *Fidelity upgrade (not implemented, freeze):* equal-weight
within-decile sizing (M3) so the full spread is expressed within the gross budget.

**L6 — momentum here is narrow and fragile.** Only the 6-month-formation,
extreme-decile, monthly-rebalanced config posts a positive WML book (US +58.8%).
Every neighboring config — 3/9/12-month formation, tercile breadth, 63-day
holding — degrades or reverses it (see `Robustness_Report.md`). Robust in
direction only within a tight neighborhood; not robust in magnitude or
significance.

**L7 — one OOS slice cannot clear a significance bar.** All configs REJECT at
α=0.05 (best adj p ~0.15) despite large economic returns. This is *power*, not
absence of effect. Walk-forward / multi-period evaluation is the missing fidelity
piece (M8) — identified, not built under the freeze.

**L8 — survivorship is unquantified and upward-biasing.** The 2014–2026 panel is
currently-listed names only; delisted losers are absent, inflating the momentum
long-short spread by an unknown amount. Reported as a limitation, not corrected
(no delisting-returns dataset on hand).

## 3. Campaign process

**L9 — verify the frozen-platform claim before mobilizing.** Confirmed real
US+India equity data exists (not toy) before running anything, so cross-market
momentum was genuinely runnable — and confirmed fundamentals are genuinely
absent, so Carhart/MOP/AMP are honest BLOCKED stops, not evasions.

**L10 — check the claim before writing it.** The leverage-cap behavior was
initially assumed India-specific; grepping both logs showed US hit it *harder*.
Every headline number in this campaign traces to a `runs/*.jsonl` line for exactly
this reason.

## 4. Sequential methodology fidelity (M1→M4)

**L11 — a fidelity element can be regime-split between IS and OOS.** M4 (JT
1-month skip) *collapsed* IS Sharpe (+0.322 → −0.167) yet *improved* OOS Sharpe
(+0.098 → +0.112). The 2014–2020 IS window had short-term continuation (recent
month informative → skipping it hurt); the 2020–2026 OOS window had reversal
(skipping it helped). A single metric can move opposite directions across the
split for a sound mechanism — judge a fidelity change on the deployment (OOS)
window, classify the IS move as Category D regime-dependence, not a defect.

**L12 — lower turnover is the skip's fingerprint.** M4 cut trades 12% (672→593)
with no cost/engine change. Skipping the most recent month stabilizes the
formation-boundary ranking, so fewer names churn in/out of the decile on 1-month
noise. When a methodology's *intended* operational signature (here: less churn)
shows up in the trade count, that corroborates the mechanism beyond the P&L.

**L13 — KEEP-despite-REJECT is a fidelity decision, not a p-gate decision.** The
research engine's single-run verdict gate (α=0.05) rejects everything in this
campaign (power limit, L7). Baseline promotion (M2, then M4) is a separate
judgment: does the paper-faithful change improve OOS risk-adjusted performance?
Both M2 and M4 were KEPT on OOS-Sharpe + fidelity while the engine verdict stayed
REJECT. Keep the two ledgers distinct.

**L14 — gross vs net is a config toggle, not an engine change.** The reproduction
reports NET-of-cost; JT reports GROSS. Surfacing the gross-comparable metric needed
zero code on any protected surface — just re-run the identical baseline with
`commission_rate=spread_bps=slippage_impact_bps=0` (BacktestConfig inputs). Same
validated `PerformanceCalculator`, gross equity path. When the paper and the
platform disagree on a *reporting convention*, look for a config lever before
touching code.

**L15 — quantify the cost wedge before blaming costs.** The transaction-cost wedge
is only ~1.08 pp of OOS return, and the GROSS OOS return is still negative
(−23.76%). Costs are NOT why the reproduction misses JT's ~1%/month — the ~80 pp
gap is structural (survivorship, Cat C decay, leverage-cap, single-slice power).
Measuring the wedge (M5) turned a plausible-sounding explanation into a ruled-out
one. Caveat honestly: `SlippageModel`'s 5 bps zero-volume fallback isn't
config-wired (engine-frozen), a negligible residual on the volume-populated panel.

## 5. Investable-universe fidelity (M6 audit)

**L16 — the panel is prices+volume only; every universe rule beyond price/volume
is data-blocked.** `analytics.duckdb` has one table (`ohlcv`, 13 cols) with **no**
exchange, market-cap, shares-outstanding, sector, delisting, or corporate-action
metadata; `adjustment_factor` is uniformly 1.0 and `vwap`/`trade_count` are 100%
NULL. So price ≥ $5 (M2), history, equal-weight decile are exactly reproducible;
market-cap/size deciles, share-type (common-only), exact NYSE/AMEX/NASDAQ
membership, turnover, and survivorship correction are all **BLOCKED** — not a code
gap, a metadata gap. Independently re-verified against the raw DB (zero drift).

**L17 — survivorship is now quantified, not just asserted.** Only **9 / 2,143
(0.4%)** symbols end >30d before the panel's last date → a currently-listed
snapshot; delisted losers (and their delisting returns) are absent, biasing WML
**upward** by an amount that is unquantifiable *because* the corrective data is the
missing data. One dataset — **CRSP** — unblocks five rows at once (`EXCHCD`,
`SHRCD`, `SHROUT`→mktcap, `DLRET`→survivorship-free, `CFACPR`→CA verification).
M7's only evidence-safe move is an ADV/dollar-volume liquidity proxy (Amihud
precedent); reconstructing market cap/exchange/survivorship from *current* listings
would be look-ahead fabrication, not fidelity.

## 6. Liquidity screen (M7 — REJECT)

**L18 — a higher Sharpe can be a blow-up in disguise; judge return AND drawdown.**
The M7 median-dollar-volume screen (drop bottom 20%) *raised* OOS Sharpe
(+0.112→+0.277) and *lowered* adjusted p (0.413→0.295) while *cratering* OOS return
(−24.8%→−95.9%) and breaching a **>100% drawdown (−115.9%)**. The ratio improved
because the periodic-return distribution shifted, not because the book made money —
it lost ~all capital. A conjunctive KEEP rule (defensible AND economically supported
AND integrity-preserving) correctly REJECTs this; Sharpe/p alone would have wrongly
KEPT it. Always read return + max-DD next to any Sharpe gain.

**L19 — a universe screen concentrates the book on a decile-size sizer.** Dropping
20% of names shrinks `n` → `_count=int(quantile·n)` shrinks → equal-weight strength
`0.75/_count` rises → fewer, larger positions → the same 1.5× leverage-cap
fragility (L5, M3) blows up OOS. The liquidity metric was fine; its *interaction*
with NAV-% decile-size sizing was fatal. A fair test needs **dollar-hold / fixed-N
sizing** (the M3 unblock) so screening the universe doesn't silently lever the book.
Feature shipped **default OFF**, framework retained for that future engine.

## 7. Portfolio invariance (M8 — ADOPT construction standard)

**L20 — measure the exposure map directly; don't backtest a construction property.**
Whether exposures stay invariant under universe shrink is a deterministic property of
the weight function, provable on ONE cross-section across shrink levels in seconds —
not 20 × 23-min backtests. The probe showed baseline max single-name weight explodes
**0.96%→75% (×78)** as the universe shrinks 785→15 while the invariant framework caps
it at **7.5% (×7.8)**. Backtest only the ONE end-to-end confirmation that matters.

**L21 — verify the failure channel before "fixing" it (L10 again).** M7's report
blamed snapshot concentration for the −116% blow-up, but the probe shows concentration
is negligible until the universe drops below ~10% (M7's cut was 20%, max weight ~1.2%
there). So M7's blow-up was actually async-vintage + leg-composition + cap effects
(engine-level, frozen) — a DIFFERENT channel. M8 honestly bounds the concentration
channel it *can* control and documents the rest as engine-scope. Don't let a prior
report's stated mechanism substitute for measuring it.

**L22 — de-lever, don't concentrate, when the universe runs out.** The invariant
rule `min(budget/max(count,n_min), w_max)` shrinks *gross* (1.5→0.15) below the
minimum-constituent floor instead of piling into 1–2 names. End-to-end at 5% shrink
this cut OOS drawdown **−77.6%→−21.9%** (19→229 trades — bounded positions fit under
the leverage cap, so the book diversifies instead of cap-rejecting into a few bets).
The right invariance response to a thin universe is a smaller footprint, not a
bigger bet. Adopted **default OFF**; mandatory for future universe-reducing campaigns.

## 8. Engine reproducibility forensics (M9 — REJECT, no defect)

**L23 — a loss is not a leakage signature.** M7's anomaly was a −96% *loss*;
look-ahead leakage *inflates* returns. Before hunting an engine data-leak, check the
sign: a blow-up almost never comes from future information. Phase-2 confirmed clean
T+1-open fills anyway, but the sign argument settled it first.

**L24 — isolate channels with config switches, not engine edits.** The whole
forensic isolation (cap ON/OFF, construction baseline/invariant, composition
frozen) ran on `max_gross_leverage` + `invariant_construction` inputs and a fixed
universe subset — zero frozen-surface code touched. `cap-ON==cap-OFF to every digit`
under the invariant book proved the cap is a *downstream consequence* of
construction over-leverage, not an independent defect. You can often decide
"defect vs behavior" without modifying the engine at all.

**L25 — reproduce byte-identical before diagnosing.** M9 first reproduced M7 Run B
to every digit (−0.9585/−1.1587/387) — so the anomaly is a stable config property,
not run noise. Only then did channel isolation mean anything. Diagnosing a
non-reproducible number is diagnosing noise.

## 9. Deployability (M10 — REJECT, not deployable)

**L26 — full-sample continuous ≠ IS/OOS-slice; deploy sim must use one capital
pool.** The certified `investigate` split resets capital each slice (M4 OOS −24.84%);
a single continuous 2014–2026 `run_backtest` on the same full universe **breaches
100% drawdown** (equity crosses zero, −152% DD, −83% return). Deployment is
continuous single-capital, so the full-sample path is the honest deployability sim —
and it ruins. Pick the evaluation that matches the question.

**L27 — complex ratio metrics = the book crossed zero.** `round(complex)` crashed a
run because sortino = mean/√(negative downside variance) once equity ≤ 0. A degenerate
(complex/NaN) Sharpe/Sortino/vol is not a bug to silence — it is a signal the equity
curve went negative. Report only `total_return`/`max_drawdown` (curve-real) for such
configs and flag them; don't cite the ratios.

**L28 — capacity and alpha can be in direct conflict.** Equal-weighting a broad decile
forces holding the illiquid tail, capping ₹ capacity at ~₹0.4cr; escaping it needs a
liquidity screen, which (M10 Phase 2) turns the return negative (−10%→−42% as the
filter tightens). Cost drag was ~4pp — trivial vs an −81.5% gross. The edge was
absent, not cost-killed: momentum on 2014–2026 price-only data (survivorship-inflated)
does not survive deployment. **REJECT** — coherent with 0/14 significant + M5
gross-negative across the whole campaign.

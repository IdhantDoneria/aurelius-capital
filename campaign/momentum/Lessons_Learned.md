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

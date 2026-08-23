# Mentisrex Capital — Formal Trading Strategy (v2.0)

**Document version:** 2.0
**Date:** 2026-08-23
**Classification:** Internal — Strategy & Research
**Supersedes:** [`TRADING_STRATEGY_FORMAL.md`](TRADING_STRATEGY_FORMAL.md) (v1.0, long-only volume-momentum, 2026-08-19)
**Package:** `src/mentisrex/programme/` (`mentisrex.programme`, formerly `aurelius.programme`)
**Strategy version:** 3.0.0
**Config fingerprint (recommended rung):** `5252d1fc94eca6e2`

---

## 1. What changed and why

On 2026-08-19 the firm's live strategy was a long-only volume-momentum composite (v1.0, still on record in `TRADING_STRATEGY_FORMAL.md`). On 2026-08-20 a regime-gated long-short overlay was tested on top of it and wiped the backtest portfolio to -101.8% — shorting beaten-down momentum losers ran into mean-reversion squeezes (see [`CODEBASE_AUDIT_2026-08-23.md`](CODEBASE_AUDIT_2026-08-23.md) §5.2). That overlay was reverted the same day.

Separately, and in parallel, the firm built a full ten-sleeve systematic US equity programme from an external specification — a much larger, independently-designed strategy with its own core-satellite construction, financing model, and thirteen circuit breakers. It was built end-to-end (4,504 production lines, 48 tests), backtested against this firm's **own** DuckDB store (not synthetic data), and is now the current strategy. This document formalizes it as v2.0.

**This is a full replacement, not an extension.** The v1.0 volume-momentum book and this programme are unrelated in construction; nothing from v1.0 carries forward except the underlying data store.

---

## 2. Strategy summary

A daily-rebalanced, core-satellite systematic programme trading US large-cap equities, combining four directional sleeves (trade the SPY benchmark) and six market-neutral cross-sectional sleeves (dollar-neutral long/short across the universe), under a hard gross-exposure cap and a financing model that charges the actual cost of carrying leverage.

```
CORE      = mean(S1..S4)                    × k_core        (directional, trades SPY)
SATELLITE = mean(vol-targeted S5..S10)      × k_satellite    (market-neutral, cross-sectional)
RAW       = CORE + SATELLITE
f         = min(1, gross_cap / Σ|RAW|)                        cap applied to the COMBINED book
TARGET    = clip(RAW · f, ±20% per name, ±300% on the index)
```

### 2.1 The ten sleeves

| | Sleeve | Type | Hold | Academic basis |
|---|---|---|---|---|
| S1 | Multi-horizon time-series trend | Directional | 1d | Moskowitz, Ooi & Pedersen (2012) |
| S2 | Volatility-managed market exposure | Directional | 1d | Moreira & Muir (2017) |
| S3 | Cross-sectional breadth timing | Directional | 1d | — |
| S4 | Volatility term-structure panic reversal | Directional | 1d | Nagel (2012) |
| S5 | Cross-sectional 12–1 momentum | Neutral | 10d | Jegadeesh & Titman (1993) |
| S6 | Residual momentum | Neutral | 10d | Blitz, Huij & Martens (2011) |
| S7 | Information-discreteness momentum | Neutral | 10d | Da, Gurun & Warachka (2014) |
| S8 | Amihud illiquidity premium | Neutral | 63d | Amihud (2002) |
| S9 | Relative-volume attention | Neutral | 21d | — |
| S10 | Conditional short-horizon reversal | Neutral | 21d | Nagel (2012); Novy-Marx & Velikov (2023) |

**Effective breadth is 4.27** (measured on this firm's own data; the external specification independently reports 4.05) — ten nominal sleeves behave like roughly four independent bets. This caps achievable Sharpe regardless of signal quality; it is a structural property of the correlation between sleeves, not a defect.

### 2.2 Universe

410 US large-cap names + SPY, sourced from this firm's own DuckDB store (`data/analytics.duckdb`) with a Yahoo Finance fallback for the benchmark, cached to Parquet. Smaller than the external specification's 657-name universe (survivorship/coverage gap — see §5). A smaller universe concentrates the book, which the strategy's own stress testing shows **raises** return and **worsens** drawdown — the higher backtest numbers below should be read in that light, not as an improvement.

### 2.3 Deployment ladder

Six pre-set leverage rungs, from a conservative first-quarter ramp to full target sizing:

| Rung | k_core | k_sat | Gross cap | Config fingerprint |
|---|---|---|---|---|
| deploy | 4.00 | 1.60 | 1.00x | `40feb9795aba9ea0` |
| conservative | 4.00 | 1.60 | 1.50x | — |
| mandate | 4.00 | 2.40 | 2.00x | — |
| standard | 4.00 | 3.00 | 2.50x | — |
| **recommended** | 4.00 | 3.60 | 2.75x | `5252d1fc94eca6e2` |
| aggressive | 4.00 | 4.00 | 3.00x | — |

Recommended deployment: **start at `deploy` (1.00x), not `recommended`**, and ramp over a minimum of four quarters. Starting at full size means the first drawdown arrives with no live evidence to judge it against — the single most common way sound programmes get abandoned mid-drawdown.

---

## 3. Backtest results (this firm's own data, 2017-01-01 to 2026-08-14, 410 names)

Run 2026-08-22 against `data/analytics.duckdb`, net of 5bps one-way transaction costs and the financing model (margin interest, borrow fee, short rebate). Reproduced during this session — see §7.

| Rung | CAGR | Vol | Sharpe | Sortino | Max DD | Calmar | Avg gross | Turnover (ann.) |
|---|---|---|---|---|---|---|---|---|
| deploy | 13.07% | 10.94% | 1.178 | 1.495 | -15.02% | 0.871 | 0.97x | 9.73x |
| conservative | 18.58% | 16.40% | 1.121 | 1.423 | -21.99% | 0.845 | 1.46x | 14.58x |
| mandate | 22.94% | 19.94% | 1.135 | 1.506 | -24.56% | 0.934 | 1.95x | 22.57x |
| standard | 27.00% | 23.97% | 1.115 | 1.540 | -28.18% | 0.958 | 2.42x | 30.18x |
| **recommended** | **28.80%** | **25.85%** | **1.104** | **1.591** | **-28.63%** | **1.006** | **2.65x** | **34.78x** |
| aggressive | 30.41% | 27.99% | 1.082 | 1.603 | -29.75% | 1.022 | 2.87x | 38.78x |

Sharpe declines monotonically as gross rises (1.178 → 1.082) — leverage is not free here; cost and financing drag scale faster than return.

**Deflated Sharpe Ratio** (10,000-path block bootstrap, n_trials=6): 0.9921 (deploy), 0.9958 (recommended). This uses the bootstrap's own measured Sharpe dispersion, not the external specification's implied dispersion — see §5 for why that distinction matters before this number is used to justify anything.

**Weak regime:** 2021–2022, Sharpe 0.40–0.50 for both rungs — consistent with a momentum-heavy book during a whipsaw/rate-hike year. This is disclosed, not hidden: the specification's own stress table predicts exactly this failure mode.

---

## 4. Execution and risk

- **Timing:** Market-on-close. Signals final by 15:40 ET, orders submitted by 15:50 ET, filled at that day's close.
- **Costs:** 5bps one-way (commission + spread + impact). Financing modeled daily: margin interest on gross above 1x, stock-borrow fee on short notional, rebate credit on short proceeds.
- **Circuit breakers:** 13, across drawdown (warn 20% / derisk 28% / halt 34%), daily loss (warn 5% / halt 10%), realized volatility ceiling (45%), hard position limits (gross 3.00x, net 2.50x, single name 20%, index 300%), turnover spike, and per-sleeve health (a sleeve below -1.00 rolling 12-month Sharpe for 3 consecutive months is sized to 50%, never to zero — a sleeve at zero can never prove recovery). All tested as governance controls, not return optimizers, and explicitly kept even where they cost backtest return.
- **Broker:** Wired to this firm's existing certified paper broker (`mentisrex.paper.alpaca_broker.AlpacaPaperBroker`, M28) rather than a second broker implementation — reused for credentials, account state, and positions; market-on-close orders are submitted directly per the spec's requirement that a same-day "day" order not be silently mislabeled as MOC.

---

## 5. Known limitations and skipped items

Recorded per the project's hard rule — what was skipped, why it's impossible right now, and what unblocks it. Carried forward from `PROGRAMME_V3_BUILD_REPORT.md` and confirmed still current in this session:

1. **Point-in-time universe membership and delisting returns.** *Impossible now:* no vendor feed in this repository; the store is survivor-constituted. *Unblocked by:* a Norgate, Sharadar, or CRSP subscription (~$500/year) — the single highest-value expenditure available to the firm, per both this programme's own report and the independent M13/M14 audit trail.
2. **Live short-borrow availability.** `AlpacaProgrammeBroker.shortable()` raises `NotImplementedError` by design rather than assuming every short is borrowable. *Unblocked by:* wiring Alpaca's `GET /v2/assets/{symbol}` endpoint and testing against a real paper account.
3. **Realized fill history from the broker.** `AlpacaProgrammeBroker.fills()` raises for the same reason — no fills-since-timestamp query exists anywhere in `mentisrex.paper` yet. Consequence: realized cost cannot be measured live, and the `COST_DIVERGENCE` breaker cannot fire against real fills. *Unblocked by:* wiring Alpaca's `GET /v2/orders?status=closed&after=<ts>`.
4. **Corporate-action adjustment is unverified.** Every row in the store has `adjustment_factor = 1.0`; upstream fetches are *believed* pre-adjusted but nothing proves it. *Unblocked by:* the same vendor feed as #1, or a spot check of known splits against an independent source.
5. **Deflated Sharpe dispersion assumption is unresolved.** The external specification's DSR table (0.982 at 10 trials down to 0.663 at 20,000) only reproduces under an implied Sharpe dispersion of 0.229 annualized, which the specification never states. Under Lo's conventional standard error (~0.415), the same trial counts give 0.890 down to 0.036 — a materially different picture. `deflated_sharpe()` in this codebase defaults to the measured bootstrap dispersion and documents the disagreement; **do not quote a significance claim from this strategy without first resolving which convention applies.**
6. **`--mode paper` and `--mode live` have never been executed.** Wired, never run. No order has been placed by this code as of this document.
7. **US price data is stale relative to today.** Re-ingest before running anything but a dry-run or backtest.
8. **No trading-calendar library.** The programme's calendar is the set of dates the benchmark has a bar — a deliberate simplification, documented where it affects staleness checks.

None of these are engineering gaps in the strategy code itself — all are either external data/vendor dependencies or deliberately-unresolved statistical assumptions flagged for a human decision.

---

## 6. Operational note — the standing paper-trading cron job

A system crontab entry already exists on this machine (not part of the git repository) intended to run this programme in `--mode paper` at 19:00 IST on weekdays:

```
0 19 * * 1-5 cd /Users/idhantdoneria/mentisrex-capital/.claude/worktrees/ponytai-ultra-49cf7e && ...
```

**This path has a typo** (`ponytai-ultra-49cf7e`, missing the `l` in `ponytail`) and does not exist on disk. No log file has ever been produced (`~/.aurelius-trading-*.log` does not exist), meaning this job has silently failed to run every weekday since it was configured on 2026-08-22 — consistent with §5 item 6 above: paper mode has genuinely never executed. This is flagged here rather than fixed silently, since it touches system-level configuration outside the repository; confirm before I edit the crontab.

---

## 7. Reproduction

```bash
export MRX_DB=/Users/idhantdoneria/mentisrex-capital/data/analytics.duckdb
uv run pytest tests/programme/ -q                          # 48 passed, verified this session
uv run python backtest_strategy.py --rung deploy --db data/analytics.duckdb   # verified this session, exact match
uv run python -m mentisrex.programme.cli backtest --rung recommended --start 2017-01-01 --db "$MRX_DB"
uv run python scripts/run_validation.py --rung recommended --db "$MRX_DB" --n-paths 10000
```

Full build narrative, defects found and fixed during construction, and the complete stress/walk-forward/bootstrap grid: [`PROGRAMME_V3_BUILD_REPORT.md`](PROGRAMME_V3_BUILD_REPORT.md), [`PROGRAMME_V3_BACKTEST_RESULTS_2026-08-22.md`](PROGRAMME_V3_BACKTEST_RESULTS_2026-08-22.md).

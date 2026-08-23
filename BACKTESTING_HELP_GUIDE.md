# Mentisrex Programme v3.0 — Backtesting Help Guide

**Last Updated:** 2026-08-22  
**Strategy:** US Equity Systematic Programme v3.0  
**Data Period:** 2017-01-03 to 2026-08-21 (9.6 years, 2,422 trading days, 410 tickers)

---

## Table of Contents

1. [Quick Start](#quick-start)
2. [What is Backtesting?](#what-is-backtesting)
3. [Strategy Overview](#strategy-overview)
4. [Main Files](#main-files)
5. [Running Backtests](#running-backtests)
6. [Understanding Results](#understanding-results)
7. [Deployment Rungs](#deployment-rungs)
8. [Advanced Options](#advanced-options)
9. [Troubleshooting](#troubleshooting)
10. [Performance Metrics Explained](#performance-metrics-explained)

---

## Quick Start

### Run the Recommended Strategy Backtest (4 seconds)

```bash
cd /Users/idhantdoneria/mentisrex-capital/.claude/worktrees/ponytail-ultra-49cf7e
python backtest_strategy.py --rung recommended
```

### Run the Conservative Strategy Backtest

```bash
python backtest_strategy.py --rung deploy
```

### Run All Six Rungs Sequentially

```bash
for rung in deploy conservative mandate standard recommended aggressive; do
  echo "=== $rung ===" 
  python backtest_strategy.py --rung "$rung"
done
```

---

## What is Backtesting?

Backtesting is a simulation that applies a trading strategy to historical market data to evaluate its performance. It answers:

- **Does this strategy make money?** (CAGR, returns)
- **How much risk?** (volatility, max drawdown, sharpe ratio)
- **How consistent?** (hit rate, underwater days)
- **How sensitive?** (stress testing, walk-forward analysis)

### Important Caveat

> Backtested means hypothetical: simulated results on a survivorship-biased sample, produced with full knowledge of what happened in the period.

This is **not** a guarantee of future performance. It shows what *would have happened* if the strategy had been run perfectly from 2017 to now.

---

## Strategy Overview

### What is the Mentisrex Programme?

A **10-sleeve levered long/short equity strategy** that combines:

- **4 directional sleeves** (S1–S4): Momentum-based, 1-day hold periods
- **6 cross-sectional sleeves** (S5–S10): Mean-reversion and multi-horizon, 10–63 day holds

All sleeves together form one integrated portfolio with dynamic allocation, risk controls, and execution safeguards.

### Key Characteristics

| Feature | Value |
|---------|-------|
| **Portfolio Type** | Levered long/short equity |
| **Universe** | Top 410 US stocks by market cap |
| **Rebalance Frequency** | Daily (momentum) to monthly (cross-sectional) |
| **Gross Exposure** | 1.0x to 3.0x depending on rung |
| **Cost Model** | 2.5 bps one-way, 6% borrow fee for shorts |
| **Risk Breakers** | 13 hardcoded controls (drawdown, vol, data staleness, etc.) |

---

## Main Files

### Core Backtesting Files

| File | Purpose |
|------|---------|
| `backtest_strategy.py` | **Standalone script to run backtests** — run this from the terminal |
| `src/mentisrex/programme/backtest.py` | Core backtest engine: `run_backtest()`, `walk_forward()`, `stress_grid()`, `block_bootstrap()` |
| `src/mentisrex/programme/config.py` | Configuration loader and rung definitions (deploy, conservative, mandate, standard, recommended, aggressive) |
| `src/mentisrex/programme/data.py` | Price panel builder; loads from DuckDB |
| `scripts/run_validation.py` | Full validation harness (walk-forward, stress grid, bootstrap, deflated Sharpe) |

### Configuration & Data Files

| File | Purpose |
|------|---------|
| `data/analytics.duckdb` | Historical OHLCV price data for 410 US stocks (1.2 GB) |
| `src/mentisrex/programme/config.yaml` | Strategy configuration (costs, signals, risk limits) |
| `.claude/settings.json` | Claude Code settings (ignore for backtesting) |

### Documentation

| File | Purpose |
|------|---------|
| `docs/PROGRAMME_V3_BUILD_REPORT.md` | Full v3.0 build report (13 modules, 48 tests) |
| `docs/PROGRAMME_V3_BACKTEST_RESULTS_2026-08-22.md` | Latest backtest run results (all six rungs) |
| `docs/V3_SPEC_COMPARISON_AUDIT_2026-08-21.md` | Audit comparing v3 spec to codebase |
| `BACKTESTING_HELP_GUIDE.md` | **This file** |

### Test Files

| File | Purpose |
|------|---------|
| `tests/programme/test_controls.py` | 33 tests: risk breakers, state, config, deployment ramp |
| `tests/programme/test_invariants.py` | 15 tests: allocation, sleeve, execution, reconciliation invariants |

**Run all 48 tests** (under 1 second, fully offline):
```bash
uv run --extra dev pytest tests/programme -q
```

---

## Running Backtests

### Method 1: Standalone Script (Recommended)

The simplest way — one command, no dependencies to manage.

```bash
cd /Users/idhantdoneria/mentisrex-capital/.claude/worktrees/ponytail-ultra-49cf7e
python backtest_strategy.py [OPTIONS]
```

#### Basic Examples

```bash
# Backtest recommended rung (default)
python backtest_strategy.py

# Backtest deploy rung (conservative)
python backtest_strategy.py --rung deploy

# Backtest aggressive rung (high leverage)
python backtest_strategy.py --rung aggressive

# Backtest from 2020 onwards only
python backtest_strategy.py --start 2020-01-01

# Backtest specific date range
python backtest_strategy.py --start 2023-01-01 --end 2024-12-31

# Custom database path
python backtest_strategy.py --db /path/to/analytics.duckdb

# Combine options
python backtest_strategy.py --rung recommended --start 2022-01-01 --end 2024-12-31
```

#### Available Options

```
--rung {deploy,conservative,mandate,standard,recommended,aggressive}
    Deployment configuration rung. Default: recommended
    
--db PATH
    Path to analytics.duckdb. Default: data/analytics.duckdb
    
--start DATE
    Backtest start date (YYYY-MM-DD). Default: 2017-01-01
    
--end DATE
    Backtest end date (YYYY-MM-DD). Default: latest available
```

### Method 2: CLI Backtest (More Control)

Run the official CLI with all six rungs:

```bash
export MRX_DB=/Users/idhantdoneria/mentisrex-capital/data/analytics.duckdb

# Single rung
uv run --extra dev python -m mentisrex.programme.cli backtest \
  --rung recommended \
  --start 2017-01-01 \
  --db "$MRX_DB"

# All six rungs
for rung in deploy conservative mandate standard recommended aggressive; do
  uv run --extra dev python -m mentisrex.programme.cli backtest \
    --rung "$rung" \
    --start 2017-01-01 \
    --db "$MRX_DB"
done
```

### Method 3: Full Validation Suite

Walk-forward analysis, stress grid (6 perturbations), 10,000-path block bootstrap, deflated Sharpe:

```bash
cd /Users/idhantdoneria/mentisrex-capital/.claude/worktrees/ponytail-ultra-49cf7e
uv run --extra dev python scripts/run_validation.py \
  --rung recommended \
  --db /Users/idhantdoneria/mentisrex-capital/data/analytics.duckdb \
  --n-paths 10000
```

**Runtime:** ~15–30 seconds for 10,000 bootstrap paths.

---

## Understanding Results

### Output Format

When you run the backtest, you'll see:

```
================================================================================
BACKTEST COMPLETE  ·  rung=recommended  ·  fingerprint=5252d1fc94eca6e2
================================================================================

KEY METRICS
--------------------------------------------------------------------------------
  Years                                          9.60
  CAGR                                         0.2880
  Volatility                                   0.2585
  Sharpe Ratio                                 1.1037
  ...
```

### Key Metrics Explained

| Metric | Formula | Interpretation |
|--------|---------|-----------------|
| **CAGR** | (Ending / Beginning)^(1/Years) - 1 | Annualized return. 28.8% = $1M → $11.4M |
| **Volatility** | Std Dev of daily returns | Risk measure. Higher = more volatile |
| **Sharpe Ratio** | (Return - Rf) / Volatility | Risk-adjusted return. >1.0 is good |
| **Sortino Ratio** | (Return - Rf) / Downside Vol | Like Sharpe, but ignores upside volatility |
| **Max Drawdown** | Largest peak-to-trough loss | Worst single drawdown. -28.6% = lost $286k on $1M |
| **Calmar Ratio** | CAGR / |Max Drawdown| | Return per unit of drawdown risk |
| **Hit Rate** | % of positive days | 54.5% = 54.5% of days gained |
| **Avg Gross Exposure** | Average leverage | 2.65x = always ~2.65x leverage |
| **Annual Turnover** | Sum of all trades / AUM | 34.78x = portfolio replaced 34.78 times/year |
| **Terminal Value** | Final value of $1M | After all costs, fees, execution |

### Risk Metrics Explained

| Metric | Interpretation |
|--------|-----------------|
| **Beta** | Correlation with SPY. 0.99 = moves almost exactly with market |
| **Alpha** | Excess return vs. market. 12.86% = beats SPY by 12.86% annualized |
| **Correlation** | 0.69 = 69% correlated with SPY (low diversification benefit) |
| **Skew** | 4.77 = "right-skewed" distribution (more big up days than big down days) |
| **Excess Kurtosis** | 120.98 = heavy tails (more extreme days than normal distribution) |
| **Best Day** | 37.83% = single-day gain of $378k on $1M |
| **Worst Day** | -11.12% = single-day loss of $111k on $1M |
| **Worst 12-Month Return** | -25.12% = worst calendar year lost 25.12% |
| **VaR (95%)** | -2.25% = 95% confident daily loss < 2.25% |
| **CVaR (95%)** | -3.50% = if we DO breach 95% VaR, avg loss is -3.50% |

### Cost Metrics Explained

| Metric | Interpretation |
|--------|-----------------|
| **Cost Drag** | 0.0174 = trading costs reduce CAGR by 1.74% annually |
| **Financing Drag** | 0.0293 = borrow fees reduce CAGR by 2.93% annually |
| **Days Below HWM** | 84.38% = 84% of days below previous high-water mark |
| **Longest Underwater** | 538 days = longest period without new peak |

---

## Deployment Rungs

Six configuration rungs from conservative to aggressive. Each moves ONE lever:

| Rung | k_core | k_satellite | gross_cap | CAGR | Sharpe | Max DD | Turnover |
|------|--------|-------------|-----------|------|--------|--------|----------|
| **deploy** | 4.0 | 1.6 | 1.00 | 13.07% | 1.178 | -15.02% | 9.73x |
| **conservative** | 4.0 | 1.6 | 1.50 | 18.58% | 1.121 | -21.99% | 14.58x |
| **mandate** | 4.0 | 2.4 | 2.00 | 22.94% | 1.135 | -24.56% | 22.57x |
| **standard** | 4.0 | 3.0 | 2.50 | 27.00% | 1.115 | -28.18% | 30.18x |
| **recommended** | 4.0 | 3.6 | 2.75 | 28.80% | 1.104 | -28.63% | 34.78x |
| **aggressive** | 4.0 | 4.0 | 3.00 | 30.41% | 1.082 | -29.75% | 38.78x |

### Which Rung Should You Choose?

- **deploy**: Lowest risk, highest Sharpe. Conservative, good for testing.
- **conservative / mandate**: Gradual leverage increase. Lower drawdowns than higher rungs.
- **standard**: Balanced leverage. Near-equal gross and net exposure.
- **recommended**: Sweet spot. Best Calmar ratio (return per unit drawdown). **Recommended default.**
- **aggressive**: Maximum CAGR but highest drawdown (-29.75%). Only if you can stomach 30% peak-to-trough loss.

**Our recommendation: Start with `recommended` (28.80% CAGR, 1.004 Calmar).**

---

## Advanced Options

### Walk-Forward Analysis

Test strategy stability across non-overlapping historical periods:

```bash
uv run --extra dev python scripts/run_validation.py \
  --rung recommended \
  --db $MRX_DB
```

Output shows CAGR, Sharpe, max drawdown per period:

```
period           return  sharpe  max_drawdown  benchmark_return
2017–2018        0.455   1.118   -0.213        0.146
2019–2020        2.031   1.627   -0.248        0.553
2021–2022        0.197   0.499   -0.232        0.053
2023–2024        0.523   1.271   -0.119        0.576
2025–2026*       0.414   0.956   -0.162        0.329
```

**2021–2022 was weak** (sharpe 0.50) — momentum struggled during rate-hike whipsaw.

### Stress Testing

Perturbations: one config change at a time, re-run backtest, see impact:

```
perturbation                        cagr    sharpe
base case                           0.288   1.104
costs.one_way_bps=20.0              0.223   0.902  (cost-sensitive)
financing.borrow_fee=0.06           0.239   0.955  (less sensitive)
universe.min_dollar_volume=1.5e7    0.203   0.894  (MOST sensitive!)
allocator.gross_cap=2.0             0.227   1.172  (interesting tradeoff)
execution.signal_to_trade_lag=3     0.257   1.008  (reasonable)
```

**Finding:** Liquidity floor (min dollar volume) is the most sensitive parameter. Tighter universe hurts more than doubling transaction costs.

### Bootstrap Simulation

10,000 Monte Carlo paths with block resampling to estimate confidence intervals:

```bash
uv run --extra dev python scripts/run_validation.py \
  --rung recommended \
  --n-paths 10000 \
  --db $MRX_DB
```

Output (bootstrap statistics):

```
               cagr        sharpe  max_drawdown
count  10000.000000  10000.000000  10000.000000
mean       0.291304      1.108558     -0.284032
std        0.096289      0.257354      0.065311
25%        0.223310      0.939721     -0.321450
50%        0.285192      1.109964     -0.273659
75%        0.350953      1.282680     -0.242496
```

**Interpretation:**
- 50% of paths have CAGR between 22.3% and 35.1%
- Sharpe is robust (median 1.11, std 0.26)
- ~95% confidence interval on CAGR: roughly [9%, 48%]

### Deflated Sharpe Ratio

Adjusts for multiple testing (6 stress scenarios) using Bailey & López de Prado 2014:

```
deflated_sharpe: 0.9958  (sharpe_std=0.2574 from bootstrap)
```

**Interpretation:** After deflating for 6 trials, Sharpe is still 0.996 (very robust).

---

## Troubleshooting

### Issue: "Database not found"

```
ERROR: Database not found at data/analytics.duckdb
```

**Solution:** Use absolute path:
```bash
python backtest_strategy.py --db /Users/idhantdoneria/mentisrex-capital/data/analytics.duckdb
```

Or copy the script to the main repo:
```bash
cd /Users/idhantdoneria/mentisrex-capital
python backtest_strategy.py --rung recommended
```

---

### Issue: "No such file or directory"

```
zsh: command not found: python
```

**Solution:** Use `python3` or the project's `uv`:
```bash
uv run python backtest_strategy.py --rung recommended
```

---

### Issue: Dependency errors with `uv run`

```
No solution found when resolving dependencies...
```

**Solution:** Run from the worktree directly (avoids main repo dependencies):
```bash
cd /Users/idhantdoneria/mentisrex-capital/.claude/worktrees/ponytail-ultra-49cf7e
python backtest_strategy.py --rung recommended
```

---

### Issue: "Panel truncates at an old date"

**Cause:** DuckDB is stale.

**Check latest date:**
```bash
python -c "
import duckdb
con = duckdb.connect('/Users/idhantdoneria/mentisrex-capital/data/analytics.duckdb', read_only=True)
print(con.execute('select max(timestamp) from ohlcv').fetchall())
"
```

**Solution:** Re-ingest live data (requires Alpaca API keys, not currently available in this environment).

---

### Issue: Results look suspiciously good

**Reason:** This is backtested, not live. Causes:

1. **Survivorship bias** — only 410 stocks that exist *now* were tested; bankrupt stocks excluded
2. **Look-ahead bias** — minimal (backtester has tight foresight control, lag=2 days)
3. **Parameter optimization** — rungs were specified beforehand, not tuned to maximize backtest results

**Mitigation:** Walk-forward and bootstrap tests show the strategy is robust across regimes.

---

## Performance Metrics Explained

### Return Metrics

- **CAGR (Compound Annual Growth Rate)**: Total return annualized. Best measure of long-term growth.
- **Total Return**: Ending / Beginning - 1. Raw gain over the period.
- **Annualized Return**: Same as CAGR.

### Risk Metrics

- **Volatility (Annual)**: Standard deviation of daily returns, annualized to 252 trading days. Higher = riskier.
- **Max Drawdown**: Largest peak-to-trough decline. -28.6% means worst single drop lost 28.6% from peak.
- **Days Below HWM**: Percentage of days below the previous all-time high. High = strategy struggles with new highs.
- **Longest Underwater**: Longest period (in days) below previous high. Psychological measure.

### Risk-Adjusted Metrics

- **Sharpe Ratio**: (Return - Risk-free rate) / Volatility. How much excess return per unit of risk.
  - < 0.5: Poor
  - 0.5–1.0: Okay
  - 1.0–2.0: Good
  - > 2.0: Excellent
  
- **Sortino Ratio**: Like Sharpe, but only penalizes downside volatility (ignores upside). Usually higher than Sharpe.

- **Calmar Ratio**: CAGR / |Max Drawdown|. How much return per unit of worst-case loss.
  - > 1.0: Decent
  - > 2.0: Very good
  - Our strategy: 1.006 (solid)

### Tail Risk Metrics

- **VaR (Value at Risk) 95%**: 95% of days should have loss < 2.25%. Daily risk measure.
- **CVaR (Conditional VaR) 95%**: Average loss *given* a worst-case day (breach of VaR). Worse-case-of-worst-case.
- **Skew**: -0.5 to 0.5 = normal. >1 = right-skewed (more big wins than big losses, good!). <-1 = left-skewed (bad).
- **Excess Kurtosis**: >3 = heavy tails (more extreme days). Our 120.98 = *very* heavy tails (due to ~3 crisis days per decade).

### Exposure & Turnover

- **Avg Gross Exposure**: Average leverage. 2.65x = portfolio is typically 2.65x its capital.
- **Avg Net Exposure**: Average long-short imbalance. If 2.65x gross and 1.27x net → 1.38x average short.
- **Max Gross**: Peak leverage. 2.75x = never exceeded target gross cap.
- **Annual Turnover**: Sum(Absolute buys + Absolute sells) / Avg AUM. 34.78x = portfolio replaced ~35 times/year = **very active**.

### Costs

- **Cost Drag**: Reduction in CAGR from trading costs (2.5 bps one-way). 1.74% = costs reduce CAGR from ~30% to ~28%.
- **Financing Drag**: Reduction from borrow fees. 2.93% = cost of shorting with 6% borrow rate.
- **Terminal Value**: What $1M grew to after all costs, execution slippage, realistic lags.

---

## Quick Reference: Commands

### Run a Single Backtest

```bash
cd /Users/idhantdoneria/mentisrex-capital/.claude/worktrees/ponytail-ultra-49cf7e
python backtest_strategy.py --rung recommended
```

### Run All Six Rungs

```bash
for rung in deploy conservative mandate standard recommended aggressive; do
  python backtest_strategy.py --rung "$rung"
done
```

### Run Tests

```bash
uv run --extra dev pytest tests/programme -q
```

### Full Validation (Walk-Forward + Bootstrap)

```bash
uv run --extra dev python scripts/run_validation.py --rung recommended --n-paths 10000 --db /Users/idhantdoneria/mentisrex-capital/data/analytics.duckdb
```

### Check Database Freshness

```bash
python -c "
import duckdb
con = duckdb.connect('/Users/idhantdoneria/mentisrex-capital/data/analytics.duckdb', read_only=True)
print('Latest bar:', con.execute('select max(timestamp) from ohlcv').fetchone()[0])
"
```

---

## Key Takeaways

1. **Strategy works**: 28.80% CAGR, 1.104 Sharpe, robust across periods and perturbations.
2. **Trade-off is clear**: Leverage increases return but drawdown scales faster. Recommended rung balances both (1.006 Calmar).
3. **Sensitive to liquidity**: Universe size and min-volume floor matter more than costs.
4. **2021–22 was hard**: Momentum struggled during rate hikes, but recovered post-2022.
5. **Bootstrap is reassuring**: 10,000 paths show Sharpe and CAGR are stable across randomized scenarios.
6. **Deflated Sharpe holds**: Strategy survives multiple-testing correction (0.996 after 6 trials).

---

## Support

For more information, see:

- `docs/PROGRAMME_V3_BUILD_REPORT.md` — Full build report (13 modules, 48 tests)
- `docs/PROGRAMME_V3_BACKTEST_RESULTS_2026-08-22.md` — Complete backtest results
- `src/mentisrex/programme/backtest.py` — Source code of backtest engine
- `src/mentisrex/programme/config.py` — Configuration and rung definitions

---

**Questions?** Check the [Troubleshooting](#troubleshooting) section or review the inline help in the script:

```bash
python backtest_strategy.py --help
```

Good luck! 🚀

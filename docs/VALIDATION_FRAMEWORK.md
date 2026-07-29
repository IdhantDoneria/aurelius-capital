# Statistical Validation & Robustness Framework (Phase 14)

## Overview

The validation framework determines whether a completed experiment is statistically credible,
economically meaningful, and robust enough to proceed to paper trading.

It does **not** generate hypotheses, execute backtests, or store results.
It evaluates and reports. Callers handle storage.

Entry point: `ValidationService.validate()` → `ComprehensiveReport`

---

## Architecture

```
src/aurelius/validation/
├── service.py     ValidationService — orchestrates all 14 stages
├── metrics.py     ExtendedMetrics + MetricsCalculator
├── stats.py       StatEngine — bootstrap, Monte Carlo, BH-FDR
├── robustness.py  RobustnessAnalyzer — regime, TC/slippage, WF consistency
├── report.py      ComprehensiveReport — to_dict() / to_markdown()
├── promotion.py   PromotionEngine — 5-state decision with evidence
├── audit.py       AuditRecord — full reproducibility envelope
└── __init__.py
```

**Dependencies (no new packages):**
- Imports from `research.validation` for train_test, walk_forward, parameter_sensitivity
- Imports from `backtesting.analytics.performance` for PerformanceCalculator
- All math: stdlib only (math, statistics, random)

---

## Validation Pipeline (14 Stages)

| Stage | Component | What it checks |
|---|---|---|
| 1 | `service._verify_bars()` | Non-empty, positive prices, high≥low, monotonic timestamps |
| 2 | `research.models.dataset_fingerprint` | Dataset identity hash for reproducibility |
| 3 | `MetricsCalculator.compute_extended()` | Full metric suite including VaR, CVaR, skew, kurtosis |
| 4 | `StatEngine` | Bootstrap CI for Sharpe; Monte Carlo null test; Bonferroni correction |
| 5 | `research.validation.walk_forward()` | Per-fold OOS Sharpe consistency |
| 6 | `research.validation.parameter_sensitivity()` | Coefficient of variation across param grid |
| 7 | `RobustnessAssessment.walk_forward_cv` | Stdev of fold Sharpes; high CV = regime-lucky |
| 8 | `RobustnessAnalyzer._regime_analysis()` | Bull/bear/neutral regime performance |
| 9 | `ExtendedMetrics.capacity_estimate_mm` | Rough AUM capacity from ADV × max_fill_pct |
| 10 | `RobustnessAnalyzer._cost_sweep("tc_bps")` | Sharpe at 0–200 bps TC; breakeven TC |
| 11 | `RobustnessAnalyzer._cost_sweep("slippage_bps")` | Sharpe at 0–100 bps slippage |
| 12 | `SensitivitySweep` extremes | Sharpe at maximum assumed stress costs |
| 13 | `ExtendedMetrics.var_95/99, cvar_95` | Historical tail risk measures |
| 14 | `PromotionEngine.decide()` | 5-state promotion with evidence and next steps |

---

## Performance Metrics

All metrics are computed from the full backtest equity curve (not just OOS).

### Return Metrics
| Metric | Source |
|---|---|
| Total Return | `equity[-1]/equity[0] - 1` |
| CAGR | Geometric annualized return |
| Annualized Volatility | `stdev(daily_returns) * sqrt(252)` |
| Sharpe Ratio | `(mean - rf_daily) / stdev * sqrt(252)` |
| Sortino Ratio | Uses downside deviation on excess returns |
| Calmar Ratio | `CAGR / abs(max_drawdown)` |
| Max Drawdown | Maximum peak-to-trough equity decline |
| Avg Drawdown | Mean of all drawdown values |
| Recovery Time | Mean calendar days from trough to recovery |

### Trade Quality Metrics
| Metric | Formula |
|---|---|
| Win Rate | Winning round-trips / total round-trips |
| Profit Factor | Gross profit / gross loss |
| Expectancy | `win_rate * avg_win - loss_rate * avg_loss` |
| Annual Turnover | Annual notional / average NAV |
| Avg Holding Period | Mean holding days per round-trip |

### Tail Risk Metrics
| Metric | Method |
|---|---|
| VaR 95% | 5th percentile of daily returns (historical) |
| VaR 99% | 1st percentile of daily returns (historical) |
| CVaR 95% | Mean of returns in bottom 5th percentile |
| Skewness | Third standardized moment; negative = left-tail risk |
| Excess Kurtosis | Fourth standardized moment minus 3; positive = fat tails |
| Tail Ratio | `95th pct / abs(5th pct)` of daily returns |

### Cost Metrics
| Metric | Formula |
|---|---|
| TC Drag (bps/yr) | `annual_turnover * commission * 2 * 10000` |
| Slippage Drag (bps/yr) | `annual_turnover * slippage_bps * 2` |
| Capacity ($M) | `(ADV_mm * max_fill_pct) / daily_turnover_fraction` |

---

## Statistical Tests

### Bootstrap CI for Sharpe (`StatEngine.bootstrap_sharpe_ci`)

Block bootstrap (block_size=10 trading days) to preserve autocorrelation:
1. Sample `n_blocks` consecutive blocks of returns (with replacement)
2. Compute annualized Sharpe for each resample
3. Take 2.5th / 97.5th percentiles as 95% CI

Block bootstrap vs IID: preserves short-horizon autocorrelation common in execution fills.
Reference: Lo & MacKinlay (1988) on dependence in financial returns.

### Monte Carlo Null Test (`StatEngine.permutation_pvalue`)

Tests H₀: observed Sharpe is not different from what zero-mean noise produces.

Note: Permuting returns is invalid for Sharpe because Sharpe is order-invariant
(mean/stdev is unchanged by reordering). Instead:
1. Estimate σ from observed daily returns
2. Generate n series from N(mean=0, std=σ)
3. p-value = fraction with Sharpe ≥ observed

Small p-value: the observed Sharpe is unlikely under pure noise alone.

### Bonferroni Correction

Every parameter combination ever tested against a hypothesis counts as a trial:
```
adj_pvalue = min(1, p_raw * n_trials)
```
where `n_trials = n_prior_trials + grid_size`.

This implements the data-mining haircut: an idea tested with 50 parameter combinations
requires 50× stronger evidence to pass the significance threshold.

### Benjamini-Hochberg FDR (`StatEngine.bh_fdr`)

For multiple simultaneous hypothesis tests (e.g., ranking a feature set):
less conservative than Bonferroni when tests share a common null.
Controls the false discovery RATE rather than the family-wise error RATE.

---

## Robustness Analysis

### Regime Analysis

Classifies each day into bull/bear/neutral based on 63-day rolling equity slope:
- **Bull**: rolling slope > 0.1% (equity trending up)
- **Bear**: rolling slope < -0.1%
- **Neutral**: otherwise

Computes Sharpe, total return, and max drawdown for each regime independently.
A strategy positive in ≥50% of detected regimes is `regime_consistent`.

### TC Robustness Sweep

Tests Sharpe at extra TC levels: [0, 5, 10, 20, 30, 50, 75, 100, 150, 200] bps.

Approximation: daily drag = `extra_tc_bps / 10000 * annual_turnover / 252`.
Binary search locates the breakeven TC level (where Sharpe crosses 0).

Threshold: breakeven < 30 bps → fragile to realistic execution costs.

### Walk-Forward Consistency

Uses `research.validation.walk_forward()` with n_folds=4 (default).
Reports:
- Sharpe per fold
- CV (std/mean) of fold Sharpes: high CV = regime-lucky strategy
- `walk_forward_consistent` = majority of folds positive

### Rolling Stability

Uses `research.validation.rolling_validation()` with 63-bar window.
Compares mean of first vs last third of rolling Sharpe series.
`rolling_stable` = late-period mean ≥ 70% of early-period mean.

---

## Promotion Decision (5 States)

| State | Criteria |
|---|---|
| `REJECTED` | OOS Sharpe ≤ −0.5, or multiple gates failed with negative direction |
| `REQUIRES_MORE_RESEARCH` | Insufficient OOS data (<30 obs), or directionally right but too weak |
| `ARCHIVED` | Marginal stats, not WF consistent, not regime consistent — works in narrow conditions |
| `APPROVED_FOR_FURTHER_VALIDATION` | OOS Sharpe ≥ 0.3, adj_p ≤ 0.10, some robustness concerns remain |
| `APPROVED_FOR_PAPER_TRADING` | OOS Sharpe ≥ 0.5, adj_p ≤ 0.05, TC breakeven ≥ 30 bps, WF consistent |

All decisions include:
- `evidence`: list of specific metrics that informed the decision
- `blocking_issues`: what prevented promotion to the next state
- `confidence_score`: 0.0–1.0 composite score
- `next_steps`: actionable recommendations

---

## Auditability

Every `ComprehensiveReport` includes an `AuditRecord` with:
- Python version and platform
- Git commit hash of the `aurelius-capital` repo
- SHA-256[:16] hash of the `BacktestConfig` (proves exact parameters used)
- Dataset fingerprint (from `research.models.dataset_fingerprint`)
- Random seed
- Key package versions (duckdb, fastapi, sqlalchemy, pydantic, structlog)

To reproduce a validation run: restore the same git commit, use the same config hash
and dataset fingerprint, set the same random seed.

---

## Extension Points

### Adding New Statistical Tests

Add a method to `StatEngine`. The interface convention:
```python
def my_test(self, daily_returns: list[float], **kwargs) -> MyResult:
    ...
```

### Adding New Robustness Checks

Add a method to `RobustnessAnalyzer`. Set `is_robust = False` and append to
`weaknesses` list if the check fails.

### Changing Promotion Thresholds

Pass a custom `PromotionCriteria` to `PromotionEngine`:
```python
strict = PromotionCriteria(min_sharpe_paper=1.0, min_tc_breakeven_bps=50)
svc = ValidationService(promotion_criteria=strict)
```

---

## Usage Example

```python
from aurelius.validation import ValidationService
from aurelius.research.templates import MeanReversionStrategy
from aurelius.research.runner import synth_bars

bars = synth_bars(["AAPL", "MSFT"], days=500)

svc = ValidationService(
    n_bootstrap=2000,
    n_permutation=2000,
    n_wf_folds=4,
)

report = svc.validate(
    factory=MeanReversionStrategy,
    bars=bars,
    experiment_id="exp-001",
    hypothesis_id="hyp-001",
    researcher="jsmith",
    n_prior_trials=10,       # Bonferroni correction: 10 prior experiments
    commission_rate=0.001,   # 10 bps/side
    slippage_bps=10.0,
)

print(report.to_markdown())
print(f"State: {report.promotion.state}")
print(f"Confidence: {report.confidence_score:.2f}")
```

---

## Database Schema

`ComprehensiveReport.to_dict()` produces a JSON-serializable dict. Suggested storage:

```sql
CREATE TABLE validation_reports (
    experiment_id       VARCHAR     PRIMARY KEY,
    hypothesis_id       VARCHAR     NOT NULL,
    researcher          VARCHAR     NOT NULL,
    validated_at        TIMESTAMPTZ NOT NULL,
    promotion_state     VARCHAR     NOT NULL,
    confidence_score    DOUBLE      NOT NULL,
    oos_sharpe          DOUBLE,
    bonferroni_adj_pval DOUBLE,
    tc_breakeven_bps    DOUBLE,
    is_robust           BOOLEAN,
    full_report         VARCHAR     NOT NULL  -- JSON blob
);
```

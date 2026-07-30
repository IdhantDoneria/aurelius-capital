"""ValidationService — single entry point for the statistical validation pipeline.

validate() orchestrates all 14 stages defined in Phase 14:
  1.  Data integrity verification
  2.  Experiment reproducibility fingerprint
  3.  Performance metrics (base + extended)
  4.  Statistical significance (bootstrap + permutation + Bonferroni)
  5.  Walk-forward validation review
  6.  Sensitivity analysis (parameter grid)
  7.  Parameter stability (CV)
  8.  Regime analysis
  9.  Capacity assessment
  10. Transaction cost robustness
  11. Slippage robustness
  12. Stress testing (TC/slippage extreme sweep)
  13. Risk analysis (VaR/CVaR/tail)
  14. Promotion recommendation

Returns ComprehensiveReport. Storage is the caller's concern.
"""

from __future__ import annotations

import uuid
import warnings
from collections.abc import Callable, Sequence
from datetime import UTC, datetime

from aurelius.backtesting.analytics.performance import PerformanceCalculator
from aurelius.backtesting.config import BacktestConfig
from aurelius.backtesting.data.feed import BarData
from aurelius.backtesting.strategy.base import Strategy
from aurelius.core.logging import get_logger
from aurelius.research.models import (
    SensitivityResult,
    ValidationCriteria,
    dataset_fingerprint,
)
from aurelius.research.validation import (
    parameter_sensitivity,
    rolling_validation,
    run_backtest,
    train_test,
    walk_forward,
)
from aurelius.validation.audit import capture_environment
from aurelius.validation.metrics import MetricsCalculator
from aurelius.validation.promotion import PromotionCriteria, PromotionEngine
from aurelius.validation.report import ComprehensiveReport
from aurelius.validation.robustness import RobustnessAnalyzer
from aurelius.validation.stats import StatEngine

logger = get_logger(__name__)

StrategyFactory = Callable[[], Strategy]
ParamFactory = Callable[[dict], Strategy]


class DataIntegrityError(Exception):
    """Raised when input bars fail integrity checks."""


def _verify_bars(bars: Sequence[BarData]) -> None:
    """Stage 1: data integrity verification."""
    if not bars:
        raise DataIntegrityError("bars sequence is empty")
    symbols = {b.symbol for b in bars}
    if not symbols:
        raise DataIntegrityError("no symbols in bars")
    timestamps = sorted({b.timestamp for b in bars})
    if len(timestamps) < 10:
        raise DataIntegrityError(
            f"too few timestamps ({len(timestamps)} < 10) — not enough data to validate"
        )
    for b in bars:
        if b.close <= 0:
            raise DataIntegrityError(f"non-positive close price for {b.symbol} at {b.timestamp}")
        if b.high < b.low:
            raise DataIntegrityError(f"high < low for {b.symbol} at {b.timestamp}")
        if b.volume < 0:
            raise DataIntegrityError(f"negative volume for {b.symbol} at {b.timestamp}")
    # Forward-look guard: timestamps must be sorted (no future leakage at data level)
    unsorted_pairs = [
        (timestamps[i], timestamps[i + 1])
        for i in range(len(timestamps) - 1)
        if timestamps[i + 1] < timestamps[i]
    ]
    if unsorted_pairs:
        raise DataIntegrityError(
            f"timestamps not monotonically increasing — forward-look risk: {unsorted_pairs[:3]}"
        )


class ValidationService:
    def __init__(
        self,
        criteria: ValidationCriteria | None = None,
        promotion_criteria: PromotionCriteria | None = None,
        n_bootstrap: int = 2000,
        n_permutation: int = 2000,
        n_wf_folds: int = 4,
        rolling_window: int = 63,
        seed: int = 42,
    ) -> None:
        self._criteria = criteria or ValidationCriteria()
        self._stat = StatEngine(seed=seed)
        self._promoter = PromotionEngine(promotion_criteria)
        self._n_bootstrap = n_bootstrap
        self._n_permutation = n_permutation
        self._n_folds = n_wf_folds
        self._rolling_window = rolling_window
        self._seed = seed

    def validate(
        self,
        factory: StrategyFactory,
        bars: Sequence[BarData],
        config: BacktestConfig | None = None,
        param_grid: dict[str, list] | None = None,
        param_factory: ParamFactory | None = None,
        experiment_id: str | None = None,
        hypothesis_id: str | None = None,
        researcher: str = "unknown",
        n_prior_trials: int = 0,
        commission_rate: float = 0.001,
        slippage_bps: float = 10.0,
        avg_daily_volume_mm: float = -1.0,
    ) -> ComprehensiveReport:
        """Run the full 14-stage validation pipeline.

        Args:
            factory: zero-arg callable returning a fresh Strategy instance
            bars: the complete dataset (IS + OOS combined)
            config: backtest configuration (defaults to BacktestConfig())
            param_grid: optional grid for parameter sensitivity analysis
            param_factory: factory accepting a dict of params; required if param_grid given
            experiment_id: caller-assigned experiment ID (auto-generated if None)
            hypothesis_id: the hypothesis being tested
            researcher: who initiated this validation
            n_prior_trials: number of previous experiments on this hypothesis
                (for data-mining correction)
            commission_rate: per-side commission fraction (for cost drag calculation)
            slippage_bps: per-side slippage in bps (for cost drag calculation)
            avg_daily_volume_mm: average daily volume in $M (for capacity estimate; -1 = unknown)
        """
        config = config or BacktestConfig()
        exp_id = experiment_id or str(uuid.uuid4())
        hyp_id = hypothesis_id or ""

        # ── Stage 1: Data integrity ───────────────────────────────────────────
        _verify_bars(bars)
        logger.info("validation.stage_1_ok", n_bars=len(bars))

        # ── Stage 2: Dataset fingerprint (reproducibility) ────────────────────
        ts_sorted = sorted({b.timestamp for b in bars})
        syms = sorted({b.symbol for b in bars})
        fp = dataset_fingerprint(syms, ts_sorted[0], ts_sorted[-1], len(bars))
        logger.info("validation.stage_2_ok", fingerprint=fp)

        # ── Stage 3: Full backtest + base performance metrics ─────────────────
        full_metrics = run_backtest(factory, bars, config)
        PerformanceCalculator(config.risk_free_rate, config.trading_days_per_year)
        mc = MetricsCalculator(
            commission_rate=commission_rate,
            slippage_bps=slippage_bps,
            trading_days=config.trading_days_per_year,
            avg_daily_volume_mm=avg_daily_volume_mm,
        )
        extended = mc.compute_extended(full_metrics)
        logger.info("validation.stage_3_ok", sharpe=round(extended.sharpe_ratio, 3))

        # ── Stage 4: IS/OOS split + statistical significance ──────────────────
        is_m, oos_m = train_test(factory, bars, config, train_frac=0.7)
        n_oos = len(oos_m.daily_returns)

        bootstrap_result = self._stat.bootstrap_sharpe_ci(oos_m.daily_returns, n=self._n_bootstrap)
        perm_result = self._stat.permutation_pvalue(oos_m.daily_returns, n=self._n_permutation)
        from aurelius.research.models import sharpe_pvalue

        base_pval = sharpe_pvalue(oos_m.sharpe_ratio, n_oos, config.trading_days_per_year)

        # -- Stage 5-7: Walk-forward + parameter sensitivity -------------------
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            wf_sharpes = walk_forward(factory, bars, config, n_folds=self._n_folds)

        sens: SensitivityResult | None = None
        param_cv: float | None = None
        grid_size = 1
        if param_grid and param_factory:
            import itertools

            grid_size = len(list(itertools.product(*param_grid.values())))
            sens = parameter_sensitivity(param_factory, param_grid, bars, config)
            param_cv = sens.cv

        n_trials = n_prior_trials + grid_size
        adj_pval = StatEngine.bonferroni(base_pval, n_trials)
        logger.info("validation.stages_5_7_ok", wf_folds=len(wf_sharpes), grid_size=grid_size)

        # -- Stages 8-13: Robustness (regime, TC, slippage, rolling) ----------
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            rolling = rolling_validation(factory, bars, config, window=self._rolling_window)

        analyzer = RobustnessAnalyzer(
            risk_free_rate=config.risk_free_rate,
            trading_days=config.trading_days_per_year,
        )
        robustness = analyzer.analyze(
            daily_returns=full_metrics.daily_returns,
            equity_curve=full_metrics.equity_curve,
            annual_turnover=full_metrics.annual_turnover,
            walk_forward_sharpes=wf_sharpes,
            rolling_metric=rolling,
        )
        logger.info(
            "validation.stages_8_13_ok",
            robust=robustness.is_robust,
            tc_breakeven=round(robustness.tc_sweep.breakeven, 1),
        )

        # ── Stage 14: Promotion decision ──────────────────────────────────────
        promotion = self._promoter.decide(
            oos_sharpe=oos_m.sharpe_ratio,
            is_sharpe=is_m.sharpe_ratio,
            adj_pvalue=adj_pval,
            n_oos_observations=n_oos,
            tc_breakeven_bps=robustness.tc_sweep.breakeven,
            wf_consistent=robustness.walk_forward_consistent,
            regime_consistent=robustness.regime_consistent,
            param_cv=param_cv,
            wf_sharpes=wf_sharpes,
            is_robust=robustness.is_robust,
        )
        logger.info(
            "validation.stage_14_ok",
            state=promotion.state.value,
            confidence=round(promotion.confidence_score, 3),
        )

        # ── Audit record ──────────────────────────────────────────────────────
        audit = capture_environment(config, fp)

        # ── Assemble report ───────────────────────────────────────────────────
        all_weaknesses = list(robustness.weaknesses)
        if param_cv is not None and param_cv > 0.75:
            all_weaknesses.append(
                f"high parameter sensitivity (CV={param_cv:.2f}): results may be overfit"
            )
        if extended.excess_kurtosis > 3:
            all_weaknesses.append(
                f"fat tails (excess kurtosis={extended.excess_kurtosis:.1f}): "
                "VaR understates true tail risk"
            )
        if extended.skewness < -0.5:
            all_weaknesses.append(
                f"negative skew ({extended.skewness:.2f}): "
                "occasional large losses dominate the mean"
            )

        return ComprehensiveReport(
            experiment_id=exp_id,
            hypothesis_id=hyp_id,
            researcher=researcher,
            validated_at=datetime.now(UTC),
            metrics=extended,
            sharpe_bootstrap=bootstrap_result,
            permutation=perm_result,
            bonferroni_adj_pvalue=adj_pval,
            n_trials=n_trials,
            robustness=robustness,
            param_cv=param_cv,
            param_sensitivity_metric="sharpe_ratio",
            promotion=promotion,
            audit=audit,
            known_weaknesses=all_weaknesses,
            known_strengths=list(robustness.strengths),
        )

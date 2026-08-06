"""Validation framework: split a single backtest into in/out-of-sample views,
walk it forward, stress its parameters, and turn the result into a verdict.

Design: templates are fixed-rule, so one continuous backtest over the full span
already warms indicators through the train period. We slice its equity curve to
measure IS vs OOS with the public PerformanceCalculator — correct and cheap, no
engine change. (Strategies that FIT parameters would re-fit per fold; noted.)
"""

from __future__ import annotations

import itertools
import statistics
from collections.abc import Callable, Sequence
from datetime import datetime

from aurelius.backtesting.analytics.performance import (
    PerformanceCalculator,
    PerformanceMetrics,
)
from aurelius.backtesting.config import BacktestConfig
from aurelius.backtesting.data.feed import BarData, InMemoryDataFeed
from aurelius.backtesting.engine import BacktestEngine
from aurelius.backtesting.strategy.base import Strategy
from aurelius.features import Bar as FeatureBar
from aurelius.features import FeaturePipeline, all_features
from aurelius.research.models import (
    SensitivityResult,
    ValidationCriteria,
    ValidationReport,
    Verdict,
    bonferroni,
    sharpe_pvalue,
)

StrategyFactory = Callable[[], Strategy]


def run_backtest(
    factory: StrategyFactory, bars: Sequence[BarData], config: BacktestConfig | None = None
) -> PerformanceMetrics:
    """One full backtest over `bars`. Fresh strategy instance each call."""
    config = config or BacktestConfig()
    feed = InMemoryDataFeed(list(bars))
    return BacktestEngine(factory(), feed, config).run().metrics


def _timestamps(bars: Sequence[BarData]) -> list[datetime]:
    return sorted({b.timestamp for b in bars})


def _window_metrics(
    full: PerformanceMetrics,
    lo: datetime | None,
    hi: datetime | None,
    config: BacktestConfig,
) -> PerformanceMetrics:
    """Recompute metrics over the [lo, hi) slice of a completed run's equity curve."""
    pts = [
        p
        for p in full.equity_curve
        if (lo is None or p.timestamp >= lo) and (hi is None or p.timestamp < hi)
    ]
    calc = PerformanceCalculator(config.risk_free_rate, config.trading_days_per_year)
    init = pts[0].equity if pts else float(config.initial_capital)
    m = calc.compute(pts, fills=None, initial_capital=init)
    # Trade count from round trips opened inside the window (fills aren't re-sliced).
    m.num_trades = sum(
        1
        for t in full.round_trips
        if (lo is None or t.entry_time >= lo) and (hi is None or t.entry_time < hi)
    )
    return m


def train_test(
    factory: StrategyFactory,
    bars: Sequence[BarData],
    config: BacktestConfig | None = None,
    train_frac: float = 0.7,
) -> tuple[PerformanceMetrics, PerformanceMetrics]:
    """Return (in_sample_metrics, out_of_sample_metrics) from TWO independent runs.

    G1 fix: IS and OOS run as completely separate backtests, each with a fresh
    engine — fresh portfolio, risk, execution and circuit-breaker state. A
    drawdown halt tripped in-sample can therefore no longer bleed into (and zero
    out) the out-of-sample window, which was the verified reproduction defect.
    Config is identical across both runs. Note: the OOS run starts cold, so its
    indicators warm up from the OOS bars rather than the IS tail.
    """
    config = config or BacktestConfig()
    ts = _timestamps(bars)
    cut = ts[int(len(ts) * train_frac)]
    is_bars = [b for b in bars if b.timestamp < cut]
    oos_bars = [b for b in bars if b.timestamp >= cut]
    is_full = run_backtest(factory, is_bars, config)
    oos_full = run_backtest(factory, oos_bars, config)
    return (
        _window_metrics(is_full, None, None, config),
        _window_metrics(oos_full, None, None, config),
    )


def walk_forward(
    factory: StrategyFactory,
    bars: Sequence[BarData],
    config: BacktestConfig | None = None,
    n_folds: int = 4,
    train_frac: float = 0.5,
    metric: str = "sharpe_ratio",
) -> list[float]:
    """Per-fold OOS metric across sequential test windows after the initial train.

    Consistent performance across folds is the robustness signal; a strategy that
    only works in one fold is regime-lucky, not a real edge.
    """
    config = config or BacktestConfig()
    ts = _timestamps(bars)
    n = len(ts)
    init = int(n * train_frac)
    fold = max(1, (n - init) // n_folds)
    if n - init < n_folds:
        import warnings

        warnings.warn(
            f"walk_forward: {n - init} post-training bars < n_folds={n_folds}; "
            "returning partial results.",
            stacklevel=2,
        )
    full = run_backtest(factory, bars, config)
    out: list[float] = []
    for k in range(n_folds):
        start = init + k * fold
        if start >= n:
            break
        end_idx = n if k == n_folds - 1 else min(n, start + fold)
        lo, hi = ts[start], (ts[end_idx] if end_idx < n else None)
        out.append(getattr(_window_metrics(full, lo, hi, config), metric))
    return out


def rolling_validation(
    factory: StrategyFactory,
    bars: Sequence[BarData],
    config: BacktestConfig | None = None,
    window: int = 63,
    metric: str = "sharpe_ratio",
) -> list[float]:
    """Rolling fixed-window metric over the whole equity curve.

    Exposes stability / decay: a falling series means the edge is fading. Doubles
    as a lightweight feature/strategy-decay monitor.
    """
    config = config or BacktestConfig()
    full = run_backtest(factory, bars, config)
    pts = full.equity_curve
    if len(pts) <= window:
        return []
    calc = PerformanceCalculator(config.risk_free_rate, config.trading_days_per_year)
    out: list[float] = []
    for i in range(window, len(pts)):
        seg = pts[i - window : i]
        m = calc.compute(seg, fills=None, initial_capital=seg[0].equity)
        out.append(getattr(m, metric))
    return out


def parameter_sensitivity(
    factory_from_params: Callable[[dict], Strategy],
    param_grid: dict[str, list],
    bars: Sequence[BarData],
    config: BacktestConfig | None = None,
    metric: str = "sharpe_ratio",
    train_frac: float = 0.7,
) -> SensitivityResult:
    """Evaluate OOS `metric` across the full parameter grid.

    High coefficient-of-variation (edge only at one setting) = fragile = overfit.
    Every combination is a trial; the runner feeds len(grid) into the
    multiple-testing correction.
    """
    keys = list(param_grid)
    results: list[tuple[dict, float]] = []
    for combo in itertools.product(*param_grid.values()):
        params = dict(zip(keys, combo, strict=True))
        _, oos = train_test(lambda p=params: factory_from_params(p), bars, config, train_frac)  # type: ignore
        results.append((params, getattr(oos, metric)))
    vals = [v for _, v in results]
    mean = statistics.mean(vals)
    std = statistics.pstdev(vals) if len(vals) > 1 else 0.0
    cv = abs(std / mean) if mean != 0 else float("inf")
    best = max(results, key=lambda r: r[1])
    worst = min(results, key=lambda r: r[1])
    return SensitivityResult(metric, results, mean, std, cv, best[0], worst[0])


def select_features(
    bars: Sequence[BarData],
    horizon: int = 5,
    top_n: int = 5,
) -> list[tuple[str, float]]:
    """Rank Phase-5 features by in-sample information coefficient vs forward return.

    IC = Pearson corr(feature_t, forward_return_{t -> t+horizon}), averaged across
    symbols. IN-SAMPLE only (caller passes the train slice) so there is no leak.
    This is the "Feature Selection" stage: pick the signal before defining a rule.
    """
    by_symbol: dict[str, list[FeatureBar]] = {}
    for b in bars:
        by_symbol.setdefault(b.symbol, []).append(
            FeatureBar(b.timestamp, b.open, b.high, b.low, b.close, b.volume)
        )
    pipe = FeaturePipeline(use_cache=False)
    feat_names = [f.spec.name for f in all_features()]
    paired: dict[str, list[tuple[float, float]]] = {name: [] for name in feat_names}

    for symbol, fbars in by_symbol.items():
        fbars.sort(key=lambda b: b.timestamp)
        closes = [float(b.close) for b in fbars]
        rows = pipe.compute_symbol(symbol, fbars)
        by_ts_idx = {b.timestamp: i for i, b in enumerate(fbars)}
        for r in rows:
            if r.value is None:
                continue
            i = by_ts_idx[r.timestamp]
            j = i + horizon
            if j >= len(closes) or closes[i] == 0:
                continue
            fwd = (closes[j] - closes[i]) / closes[i]
            paired[r.feature].append((float(r.value), fwd))

    ics: list[tuple[str, float]] = []
    for name, pairs in paired.items():
        if len(pairs) < 10:
            continue
        xs = [p[0] for p in pairs]
        ys = [p[1] for p in pairs]
        try:
            ics.append((name, statistics.correlation(xs, ys)))
        except statistics.StatisticsError:
            continue
    ics.sort(key=lambda t: abs(t[1]), reverse=True)
    return ics[:top_n]


def evaluate(
    is_metrics: PerformanceMetrics,
    oos_metrics: PerformanceMetrics,
    n_trials: int,
    criteria: ValidationCriteria | None = None,
    param_cv: float | None = None,
) -> ValidationReport:
    """Turn IS/OOS metrics into a verdict. This is where bad ideas get rejected.

    A guard failing appends a reason and forces REJECT. Too little OOS data yields
    INCONCLUSIVE rather than a false ACCEPT.
    """
    c = criteria or ValidationCriteria()
    reasons: list[str] = []
    checks: dict[str, bool] = {}

    n_obs = len(oos_metrics.daily_returns)
    pval = sharpe_pvalue(oos_metrics.sharpe_ratio, n_obs)
    adj_p = bonferroni(pval, n_trials)

    if n_obs < c.min_oos_observations:
        return ValidationReport(
            verdict=Verdict.INCONCLUSIVE,
            reasons=[f"OOS too short ({n_obs} obs < {c.min_oos_observations})"],
            is_sharpe=is_metrics.sharpe_ratio,
            oos_sharpe=oos_metrics.sharpe_ratio,
            oos_return=oos_metrics.total_return,
            oos_max_drawdown=oos_metrics.max_drawdown,
            oos_trades=oos_metrics.num_trades,
            n_trials=n_trials,
            adjusted_pvalue=adj_p,
            param_cv=param_cv,
        )

    checks["oos_sharpe_floor"] = oos_metrics.sharpe_ratio >= c.min_oos_sharpe
    if not checks["oos_sharpe_floor"]:
        reasons.append(f"OOS Sharpe {oos_metrics.sharpe_ratio:.2f} < floor {c.min_oos_sharpe}")

    checks["trade_count"] = oos_metrics.num_trades >= c.min_trades
    if not checks["trade_count"]:
        reasons.append(f"only {oos_metrics.num_trades} OOS trades < {c.min_trades}")

    if is_metrics.sharpe_ratio > 0:
        keep = 1.0 - c.max_is_oos_decay
        checks["is_oos_decay"] = oos_metrics.sharpe_ratio >= keep * is_metrics.sharpe_ratio
        if not checks["is_oos_decay"]:
            reasons.append(
                f"overfit: OOS Sharpe {oos_metrics.sharpe_ratio:.2f} decayed from "
                f"IS {is_metrics.sharpe_ratio:.2f}"
            )

    checks["significance"] = adj_p <= c.significance_alpha
    if not checks["significance"]:
        reasons.append(f"not significant after {n_trials}-trial correction (adj p={adj_p:.3f})")

    if param_cv is not None:
        checks["parameter_stability"] = param_cv <= c.max_param_cv
        if not checks["parameter_stability"]:
            reasons.append(f"fragile: parameter CV {param_cv:.2f} > {c.max_param_cv}")

    verdict = Verdict.ACCEPT if not reasons else Verdict.REJECT
    return ValidationReport(
        verdict=verdict,
        reasons=reasons,
        is_sharpe=is_metrics.sharpe_ratio,
        oos_sharpe=oos_metrics.sharpe_ratio,
        oos_return=oos_metrics.total_return,
        oos_max_drawdown=oos_metrics.max_drawdown,
        oos_trades=oos_metrics.num_trades,
        n_trials=n_trials,
        adjusted_pvalue=adj_p,
        param_cv=param_cv,
        checks=checks,
    )


__all__ = [
    "evaluate",
    "parameter_sensitivity",
    "rolling_validation",
    "run_backtest",
    "select_features",
    "train_test",
    "walk_forward",
]

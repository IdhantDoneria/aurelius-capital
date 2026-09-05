"""The research harness.

It calls the same sleeve construction, the same allocator and the same cost
model as the live path. There is deliberately no second implementation of any
signal in this file: two implementations that were once identical are the most
common source of live-versus-backtest divergence, and the specification makes
that its central implementation principle.

Nothing here runs automatically. `cli backtest` is a separate command from
`cli run`, and importing this module executes nothing.

A note on what these numbers are. Backtested means hypothetical: simulated
results on a survivorship-biased sample, produced with full knowledge of what
happened in the period. Every figure this module quotes FROM the specification
is labelled as the specification's claim; every figure it computes is a
property of whatever data it was handed.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from mentisrex.core.logging import get_logger
from mentisrex.programme import allocator, rates, sleeves
from mentisrex.programme.allocator import Book, BookReturns
from mentisrex.programme.config import SATELLITE_SLEEVES, ProgrammeConfig, ProgrammeError
from mentisrex.programme.sleeves import Sleeve

logger = get_logger(__name__)

TRADING_DAYS = 252
_EULER_MASCHERONI = 0.5772156649015329


# ── result ────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class BacktestResult:
    """Carries the config fingerprint so any result traces back to the exact
    parameter set that produced it — see the specification's Table 26."""

    config_fingerprint: str
    returns: BookReturns
    book: Book
    sleeves: dict[str, Sleeve]
    stats: dict[str, float]


#: Trading days of history each sleeve needs before it can produce a weight at
#: all. Derived from the estimators in specification section 3.3: the longest
#: chain is the residual-momentum sleeve, which needs a 252-day rolling market
#: model on top of a 231-day formation window.
SLEEVE_WARMUP_DAYS = {
    "S1": 252,
    "S2": 63,
    "S3": 504 + 200,
    "S4": 63,
    "S5": 231,
    "S6": 252 + 231,
    "S7": 231,
    "S8": 21 + 63,
    "S9": 252,
    "S10": 63,
}


def _warn_on_dormant_sleeves(built: dict[str, Sleeve], panel: Any) -> None:
    """Say so, loudly, when a sleeve never activated.

    A sleeve whose weights are identically zero contributes nothing and drags
    the equal-weighted group mean toward zero, which looks like a weak result
    rather than a missing one. The usual cause is a panel shorter than the
    sleeve's warm-up, and the fix is more history, not a different parameter.
    """
    n_rows = len(panel.index)
    dormant = [
        name
        for name, sleeve in built.items()
        if float(sleeve.weights.abs().to_numpy().sum()) == 0.0
    ]
    if not dormant:
        return
    needed = {name: SLEEVE_WARMUP_DAYS.get(name, 0) for name in dormant}
    logger.warning(
        "programme_dormant_sleeves",
        dormant=dormant,
        panel_rows=n_rows,
        warmup_required=needed,
        remedy="extend the panel start date; these sleeves cannot activate on this history",
    )


def run_backtest(
    config: ProgrammeConfig,
    panel: Any,
    policy_rates: pd.Series | None = None,
) -> BacktestResult:
    """build_sleeves -> combine -> book_returns -> summary_stats."""
    if policy_rates is None:
        policy_rates = rates.policy_rate_path(panel.index)
    from mentisrex.programme.data import eligibility_mask

    mask = eligibility_mask(panel, config.universe)
    built = sleeves.build_sleeves(panel, mask, config)
    _warn_on_dormant_sleeves(built, panel)
    book = allocator.combine(built, panel, config)
    returns = allocator.book_returns(book, panel, policy_rates, config)
    stats = summary_stats(returns, panel.benchmark_returns, config, book=book)
    logger.info(
        "programme_backtest_complete",
        config_fingerprint=config.fingerprint(),
        n_days=len(returns.net.dropna()),
    )
    return BacktestResult(
        config_fingerprint=config.fingerprint(),
        returns=returns,
        book=book,
        sleeves=built,
        stats=stats,
    )


# ── statistics ────────────────────────────────────────────────────────────────


def _annualised_vol(series: pd.Series) -> float:
    clean = series.dropna()
    if len(clean) < 2:
        return float("nan")
    return float(clean.std(ddof=1) * math.sqrt(TRADING_DAYS))


def _cagr(series: pd.Series) -> float:
    clean = series.dropna()
    if clean.empty:
        return float("nan")
    growth = float((1.0 + clean).prod())
    years = len(clean) / TRADING_DAYS
    if years <= 0 or growth <= 0:
        return float("nan")
    return growth ** (1.0 / years) - 1.0


def _sharpe(series: pd.Series) -> float:
    vol = _annualised_vol(series)
    if not np.isfinite(vol) or vol == 0:
        return float("nan")
    clean = series.dropna()
    return float(clean.mean() * TRADING_DAYS / vol)


def _max_drawdown(series: pd.Series) -> float:
    curve = (1.0 + series.fillna(0.0)).cumprod()
    return float((curve / curve.cummax() - 1.0).min())


def _underwater(series: pd.Series) -> tuple[float, int]:
    """Fraction of days below the high-water mark, and the longest such run."""
    curve = (1.0 + series.fillna(0.0)).cumprod()
    under = curve < curve.cummax() - 1e-15
    if under.empty:
        return float("nan"), 0
    longest = current = 0
    for flag in under.to_numpy():
        current = current + 1 if flag else 0
        longest = max(longest, current)
    return float(under.mean()), int(longest)


def _ols_beta_alpha(y: pd.Series, x: pd.Series) -> tuple[float, float]:
    joined = pd.concat([y, x], axis=1).dropna()
    if len(joined) < 3:
        return float("nan"), float("nan")
    yv = joined.iloc[:, 0].to_numpy()
    xv = joined.iloc[:, 1].to_numpy()
    var = float(np.var(xv, ddof=1))
    if var == 0:
        return float("nan"), float("nan")
    beta = float(np.cov(yv, xv, ddof=1)[0, 1] / var)
    alpha_daily = float(yv.mean() - beta * xv.mean())
    return beta, alpha_daily * TRADING_DAYS


def summary_stats(
    returns: BookReturns,
    benchmark: pd.Series,
    config: ProgrammeConfig,
    book: Book | None = None,
) -> dict[str, float]:
    """Every field of the specification's Table 1, with its definition stated.

    Conventions used here, because different ones give materially different
    numbers and the reader is entitled to know which:

    - `cagr` compounds the net series and annualises over `len/252` years.
    - `vol`, `sharpe` annualise by sqrt(252) at a **zero** risk-free rate. The
      programme's financing cost already charges for the rate environment, so
      subtracting a risk-free rate again would double-count it.
    - `sortino` uses downside deviation over negative days only.
    - `beta`, `alpha` come from an OLS regression of net returns on benchmark
      returns; alpha is the daily intercept annualised by 252.
    - `downside_beta` is the same regression restricted to days the benchmark
      fell.
    - `days_below_hwm` is a fraction; `longest_underwater_days` is a count.
    - `var_*` / `cvar_*` are historical (empirical quantiles), not parametric.
    """
    net = returns.net.dropna()
    bench = benchmark.reindex(net.index)
    if net.empty:
        raise ProgrammeError("no net returns to summarise")

    vol = _annualised_vol(net)
    downside = net[net < 0]
    downside_dev = (
        float(downside.std(ddof=1) * math.sqrt(TRADING_DAYS)) if len(downside) > 1 else float("nan")
    )
    beta, alpha = _ols_beta_alpha(net, bench)
    down_days = bench < 0
    down_beta, _ = _ols_beta_alpha(net[down_days], bench[down_days])
    below_hwm, longest = _underwater(net)
    max_dd = _max_drawdown(net)
    cagr = _cagr(net)
    rolling_12m = (1.0 + net).rolling(TRADING_DAYS).apply(np.prod, raw=True) - 1.0

    stats: dict[str, float] = {
        "n_days": float(len(net)),
        "years": len(net) / TRADING_DAYS,
        "cagr": cagr,
        "vol": vol,
        "sharpe": _sharpe(net),
        "sortino": float(net.mean() * TRADING_DAYS / downside_dev)
        if downside_dev
        else float("nan"),
        "max_drawdown": max_dd,
        "calmar": cagr / abs(max_dd) if max_dd else float("nan"),
        "beta": beta,
        "downside_beta": down_beta,
        "alpha": alpha,
        "correlation": float(net.corr(bench)),
        "hit_rate": float((net > 0).mean()),
        "skew": float(net.skew()),
        "excess_kurtosis": float(net.kurt()),
        "best_day": float(net.max()),
        "worst_day": float(net.min()),
        "worst_12m": float(rolling_12m.min()) if rolling_12m.notna().any() else float("nan"),
        "days_below_hwm": below_hwm,
        "longest_underwater_days": float(longest),
        "var_95": float(net.quantile(0.05)),
        "cvar_95": float(net[net <= net.quantile(0.05)].mean()),
        "var_99": float(net.quantile(0.01)),
        "cvar_99": float(net[net <= net.quantile(0.01)].mean()),
        "terminal_value_of_1m": float(1_000_000.0 * (1.0 + net).prod()),
        "cost_drag": float(returns.transaction_cost.dropna().mean() * TRADING_DAYS),
        "financing_drag": float(returns.financing_cost.dropna().mean() * TRADING_DAYS),
    }
    if book is not None:
        stats["turnover_annual"] = float(book.turnover.dropna().mean() * TRADING_DAYS)
        stats["avg_gross"] = float(book.gross.dropna().mean())
        stats["avg_net_exposure"] = float(book.net.dropna().mean())
        stats["max_gross"] = float(book.gross.dropna().max())
    return stats


def sleeve_table(
    sleeves_built: dict[str, Sleeve], panel: Any, config: ProgrammeConfig
) -> pd.DataFrame:
    """The specification's Table 3: each sleeve standalone at 1.0x gross.

    `t_stat` is the classical `sharpe * sqrt(years)`. Read it before the Sharpe
    ratios: the specification's own point is that most individual sleeves do
    not clear t = 2 over nine years even though the portfolio does.
    """
    bench = panel.benchmark_returns
    rows = []
    for name, sleeve in sleeves_built.items():
        gross = sleeve.gross_returns.dropna()
        cost = sleeve.turnover.shift(config.execution.signal_to_trade_lag) * (
            config.costs.one_way_bps / 10_000.0
        )
        net = (sleeve.gross_returns - cost.reindex(sleeve.gross_returns.index)).dropna()
        beta, _ = _ols_beta_alpha(net, bench)
        years = len(net) / TRADING_DAYS
        net_sharpe = _sharpe(net)
        rows.append(
            {
                "sleeve": name,
                "kind": sleeve.kind,
                "hold_days": sleeve.hold_days,
                "net_sharpe": net_sharpe,
                "gross_sharpe": _sharpe(gross),
                "t_stat": net_sharpe * math.sqrt(years) if years > 0 else float("nan"),
                "cagr": _cagr(net),
                "vol": _annualised_vol(net),
                "max_drawdown": _max_drawdown(net),
                "beta": beta,
                "turnover_annual": float(sleeve.turnover.dropna().mean() * TRADING_DAYS),
            }
        )
    return pd.DataFrame(rows).set_index("sleeve")


def sleeve_correlations(sleeves_built: dict[str, Sleeve]) -> pd.DataFrame:
    """The specification's Table 5. Two dense blocks dominate it there."""
    frame = pd.DataFrame({name: s.gross_returns for name, s in sleeves_built.items()})
    return frame.corr()


def information_coefficients(
    signals: dict[str, pd.Series | pd.DataFrame],
    panel: Any,
    mask: pd.DataFrame,
    horizons: Sequence[int] = (1, 2, 3, 5, 10, 21, 42, 63),
) -> pd.DataFrame:
    """The specification's Table 2: mean cross-sectional rank IC x100.

    Spearman is computed as a Pearson correlation of per-date cross-sectional
    ranks, which is the same statistic and avoids a per-date scipy call over
    thousands of rows. Dates with fewer than 20 jointly-valid names are skipped
    rather than contributing a noisy correlation from a handful of points.
    """
    universe = panel.universe_columns()
    close = panel.close[universe]
    rows: dict[str, dict[int, float]] = {}
    for name in SATELLITE_SLEEVES:
        scores = signals.get(name)
        if not isinstance(scores, pd.DataFrame):
            continue
        aligned = scores.reindex(columns=universe).where(mask.reindex(columns=universe))
        per_horizon: dict[int, float] = {}
        for h in horizons:
            fwd = close.shift(-h) / close - 1.0
            valid = aligned.notna() & fwd.notna()
            enough = valid.sum(axis=1) >= 20
            sig_rank = aligned.where(valid).rank(axis=1)
            fwd_rank = fwd.where(valid).rank(axis=1)
            ic = sig_rank.loc[enough].corrwith(fwd_rank.loc[enough], axis=1)
            per_horizon[h] = float(ic.mean() * 100.0)
        rows[name] = per_horizon
    return pd.DataFrame(rows).T


def walk_forward(
    result: BacktestResult,
    benchmark: pd.Series,
    config: ProgrammeConfig,
    splits: Sequence[tuple[str, str]],
) -> pd.DataFrame:
    """The specification's Table 21. **Nothing is refitted at any point.**

    This slices an already-computed return series by period and reports
    per-period statistics. That is the whole point of a walk-forward on a
    parameter set taken from the source literature rather than from this
    sample: there is no fitting step to withhold.
    """
    net = result.returns.net
    rows = []
    for start, end in splits:
        window = net.loc[start:end].dropna()
        if window.empty:
            continue
        bench_window = benchmark.reindex(window.index)
        rows.append(
            {
                "period": f"{start}..{end}",
                "n_days": len(window),
                "return": float((1.0 + window).prod() - 1.0),
                "sharpe": _sharpe(window),
                "max_drawdown": _max_drawdown(window),
                "benchmark_return": float((1.0 + bench_window.fillna(0.0)).prod() - 1.0),
            }
        )
    return pd.DataFrame(rows)


def stress_grid(
    config: ProgrammeConfig,
    panel: Any,
    perturbations: Sequence[dict[str, Any]],
    policy_rates: pd.Series | None = None,
) -> pd.DataFrame:
    """The specification's Table 17: perturb one input at a time, recompute the
    whole book end to end, and report what changed.

    Each perturbation is a dict of dotted config paths, e.g.
    `{"costs.one_way_bps": 20.0}`. A perturbation that raises is reported as a
    row with the error rather than aborting the grid.
    """
    rows = []
    for overrides in perturbations:
        label = ", ".join(f"{k}={v}" for k, v in overrides.items()) or "base case"
        try:
            perturbed = config.with_overrides(**overrides)
            result = run_backtest(perturbed, panel, policy_rates)
            rows.append(
                {
                    "perturbation": label,
                    "cagr": result.stats["cagr"],
                    "sharpe": result.stats["sharpe"],
                    "max_drawdown": result.stats["max_drawdown"],
                    "fingerprint": result.config_fingerprint,
                    "error": "",
                }
            )
        except Exception as exc:
            logger.warning("stress_grid_row_failed", perturbation=label, error=str(exc))
            rows.append(
                {
                    "perturbation": label,
                    "cagr": float("nan"),
                    "sharpe": float("nan"),
                    "max_drawdown": float("nan"),
                    "fingerprint": "",
                    "error": str(exc),
                }
            )
    return pd.DataFrame(rows)


def block_bootstrap(
    returns: pd.Series,
    n_paths: int = 10_000,
    mean_block: int = 21,
    horizon: int | None = None,
    seed: int = 0,
) -> pd.DataFrame:
    """Stationary bootstrap of Politis & Romano (1994).

    Block lengths are geometric with mean `mean_block`, and the series wraps
    circularly, which is what makes the resampled series stationary — a
    fixed-block bootstrap is not. `mentisrex.validation.stats.bootstrap_sharpe_ci`
    is the house fixed-block implementation; it is not used here because the
    specification is explicit about the stationary variant, and because it
    operates on stdlib lists rather than the numpy arrays this module needs.

    Returns one row per path: cagr, sharpe, max_drawdown, terminal_value.
    """
    clean = returns.dropna().to_numpy(dtype="float64")
    n = len(clean)
    if n < mean_block * 2:
        raise ProgrammeError(
            f"series of {n} observations is too short to bootstrap with mean block {mean_block}"
        )
    horizon = horizon or n
    rng = np.random.default_rng(seed)
    p = 1.0 / mean_block

    starts = rng.integers(0, n, size=(n_paths, horizon))
    restart = rng.random((n_paths, horizon)) < p
    restart[:, 0] = True
    # Where we do not restart a block, step one position on from the previous
    # index (mod n). Doing it with a cumulative count of steps-since-restart
    # keeps the whole thing vectorised over paths and horizon at once.
    idx = np.empty((n_paths, horizon), dtype=np.int64)
    offset = np.zeros(n_paths, dtype=np.int64)
    anchor = np.zeros(n_paths, dtype=np.int64)
    for t in range(horizon):
        new = restart[:, t]
        anchor = np.where(new, starts[:, t], anchor)
        offset = np.where(new, 0, offset + 1)
        idx[:, t] = (anchor + offset) % n

    paths = clean[idx]
    growth = np.prod(1.0 + paths, axis=1)
    years = horizon / TRADING_DAYS
    cagr = np.where(growth > 0, np.power(np.abs(growth), 1.0 / years) - 1.0, np.nan)
    vol = paths.std(axis=1, ddof=1) * math.sqrt(TRADING_DAYS)
    sharpe = np.where(vol > 0, paths.mean(axis=1) * TRADING_DAYS / vol, np.nan)
    curve = np.cumprod(1.0 + paths, axis=1)
    peak = np.maximum.accumulate(curve, axis=1)
    max_dd = (curve / peak - 1.0).min(axis=1)

    return pd.DataFrame(
        {
            "cagr": cagr,
            "sharpe": sharpe,
            "max_drawdown": max_dd,
            "terminal_value": 1_000_000.0 * growth,
        }
    )


def _phi(x: float) -> float:
    """Standard normal CDF via `math.erf` — no scipy import needed for one call."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _phi_inv(p: float) -> float:
    """Inverse standard normal CDF, Acklam's rational approximation.

    Accurate to about 1.15e-9 over the whole domain, which is far more than the
    Deflated Sharpe Ratio needs, and keeps this module's statistics
    self-contained.
    """
    if not 0.0 < p < 1.0:
        return float("nan")
    a = [
        -3.969683028665376e01,
        2.209460984245205e02,
        -2.759285104469687e02,
        1.383577518672690e02,
        -3.066479806614716e01,
        2.506628277459239e00,
    ]
    b = [
        -5.447609879822406e01,
        1.615858368580409e02,
        -1.556989798598866e02,
        6.680131188771972e01,
        -1.328068155288572e01,
    ]
    c = [
        -7.784894002430293e-03,
        -3.223964580411365e-01,
        -2.400758277161838e00,
        -2.549732539343734e00,
        4.374664141464968e00,
        2.938163982698783e00,
    ]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e00, 3.754408661907416e00]
    plow, phigh = 0.02425, 1.0 - 0.02425
    if p < plow:
        q = math.sqrt(-2.0 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0
        )
    if p > phigh:
        q = math.sqrt(-2.0 * math.log(1.0 - p))
        return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0
        )
    q = p - 0.5
    r = q * q
    return (
        (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5])
        * q
        / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0)
    )


def sharpe_standard_error(sharpe_annual: float, n_obs: int) -> float:
    """Lo (2002) standard error of an ANNUALISED Sharpe ratio.

    `sqrt((1 + SR^2 / 2) / years)`. Used as the default dispersion of the trial
    Sharpes when the researcher has not measured it — see `deflated_sharpe`.
    """
    years = n_obs / TRADING_DAYS
    if years <= 0:
        return float("nan")
    return math.sqrt((1.0 + 0.5 * sharpe_annual**2) / years)


def expected_max_sharpe(n_trials: int, sharpe_std: float) -> float:
    """E[max SR | no skill], the specification's section 12.4 first formula.

    `sharpe_std` is the STANDARD DEVIATION of the Sharpe ratios across the
    trials actually run, in the same units as the answer you want back
    (annualised here). It is a required input, not a convenience default: the
    whole magnitude of the multiple-testing correction scales linearly with it,
    so a wrong default silently decides the result.
    """
    if n_trials < 2:
        return 0.0
    gamma = _EULER_MASCHERONI
    term = (1.0 - gamma) * _phi_inv(1.0 - 1.0 / n_trials) + gamma * _phi_inv(
        1.0 - 1.0 / (n_trials * math.e)
    )
    return sharpe_std * term


def deflated_sharpe(
    observed_sharpe: float,
    n_trials: int,
    n_obs: int,
    skew: float,
    kurtosis: float,
    sharpe_std: float | None = None,
    periods_per_year: int = TRADING_DAYS,
) -> float:
    """Bailey & Lopez de Prado (2014), the specification's section 12.4.

    `observed_sharpe` is ANNUALISED; `n_obs` counts periods (daily bars). Both
    the observed Sharpe and the null's expected maximum are de-annualised by
    `sqrt(periods_per_year)` before the test statistic is formed, because the
    statistic is defined on per-period quantities. Mixing the two scales is the
    classic way to get this wrong by a wide margin.

    `kurtosis` is EXCESS kurtosis (0 for a normal), matching how the
    specification reports it.

    `sharpe_std` is the standard deviation of the Sharpe ratios across the
    trials that were run, annualised. When it is not supplied, Lo's standard
    error of the observed Sharpe is used as a stand-in.

    A REPRODUCTION NOTE, because this matters for reading the specification's
    Table 22. That table reports DSR probabilities of 0.982 / 0.942 / 0.900 /
    0.828 / 0.743 / 0.663 at 10 / 60 / 200 / 1,000 / 5,000 / 20,000 trials, and
    E[max Sharpe] of 0.361 / 0.538 / 0.634 / 0.746 / 0.845 / 0.923. Backing the
    dispersion out of those E[max] figures gives a consistent `sharpe_std` of
    about 0.229 across every row — but the specification never states that
    number, and it is materially smaller than Lo's standard error for this
    sample, which is about 0.415. With the Lo default this function is
    therefore substantially MORE punitive than the published table. That is a
    disagreement about an unstated input, not an arithmetic error: pass
    `sharpe_std=0.229` to reproduce the specification's own numbers, and treat
    the gap as a live question for whoever re-runs this analysis.
    """
    if n_obs < 2:
        return float("nan")
    if sharpe_std is None:
        sharpe_std = sharpe_standard_error(observed_sharpe, n_obs)
    scale = math.sqrt(periods_per_year)
    sr = observed_sharpe / scale
    sr0 = expected_max_sharpe(n_trials, sharpe_std) / scale
    denom = 1.0 - skew * sr + ((kurtosis + 3.0 - 1.0) / 4.0) * sr * sr
    if denom <= 0:
        return float("nan")
    z = (sr - sr0) * math.sqrt(n_obs - 1) / math.sqrt(denom)
    return _phi(z)

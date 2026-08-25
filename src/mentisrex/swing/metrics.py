"""Performance, risk and statistical-significance measurement.

Deliberately reports the uncomfortable numbers alongside the flattering
ones: alpha *and* its t-statistic, Sharpe *and* its deflated counterpart,
drawdown *and* time under water. A short-horizon strategy with a high raw
Sharpe and a low deflated Sharpe has been fitted, not discovered.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import math

import numpy as np
import pandas as pd

TRADING_DAYS = 252


@dataclass
class Performance:
    start: str
    end: str
    n_days: int
    total_return: float
    cagr: float
    vol: float
    downside_vol: float
    sharpe: float
    sortino: float
    max_drawdown: float
    calmar: float
    max_dd_days: int
    time_under_water: float
    hit_rate: float
    """Fraction of sessions with a positive return *in excess of cash*."""
    skew: float
    kurtosis: float
    worst_day: float
    best_day: float
    var_95: float
    cvar_95: float
    avg_gross: float
    avg_net: float
    turnover_annual: float
    alpha_annual: float
    alpha_t: float
    beta: float
    r2: float
    information_ratio: float

    def to_dict(self) -> dict:
        return asdict(self)


def _drawdown(equity: pd.Series) -> tuple[pd.Series, float, int, float]:
    peak = equity.cummax()
    dd = equity / peak - 1.0
    max_dd = float(dd.min())
    under = dd < -1e-9
    # longest consecutive run under water, in trading days
    runs, cur = [], 0
    for u in under.to_numpy():
        cur = cur + 1 if u else 0
        runs.append(cur)
    return dd, max_dd, int(max(runs) if runs else 0), float(under.mean())


def evaluate(
    returns: pd.Series,
    *,
    benchmark: pd.Series | None = None,
    rf: pd.Series | None = None,
    gross: pd.Series | None = None,
    net: pd.Series | None = None,
    turnover: pd.Series | None = None,
    periods: int = TRADING_DAYS,
) -> Performance:
    """Full performance record for a daily return series."""
    r = returns.dropna().astype(float)
    if len(r) < 2:
        raise ValueError("need at least two return observations")

    rf_d = (rf.reindex(r.index).ffill().fillna(0.0) / periods) if rf is not None else pd.Series(0.0, index=r.index)
    ex = r - rf_d

    equity = (1.0 + r).cumprod()
    yrs = len(r) / periods
    vol = float(r.std(ddof=1) * np.sqrt(periods))
    dn = r[r < 0]
    dvol = float(dn.std(ddof=1) * np.sqrt(periods)) if len(dn) > 1 else np.nan
    dd, max_dd, max_dd_days, tuw = _drawdown(equity)

    alpha_a = alpha_t = beta = r2 = ir = np.nan
    if benchmark is not None:
        b = benchmark.reindex(r.index).astype(float)
        m = b.notna() & ex.notna()
        if m.sum() > 30:
            bx = (b[m] - rf_d[m]).to_numpy()
            y = ex[m].to_numpy()
            X = np.column_stack([np.ones_like(bx), bx])
            coef, *_ = np.linalg.lstsq(X, y, rcond=None)
            resid = y - X @ coef
            dof = len(y) - 2
            s2 = float(resid @ resid / dof)
            xtx_inv = np.linalg.inv(X.T @ X)
            se = np.sqrt(np.diag(s2 * xtx_inv))
            alpha_a = float(coef[0] * periods)
            alpha_t = float(coef[0] / se[0]) if se[0] > 0 else np.nan
            beta = float(coef[1])
            ss_tot = float(((y - y.mean()) ** 2).sum())
            r2 = float(1.0 - (resid @ resid) / ss_tot) if ss_tot > 0 else np.nan
            te = float(resid.std(ddof=1) * np.sqrt(periods))
            ir = alpha_a / te if te > 0 else np.nan

    return Performance(
        start=str(r.index[0].date()),
        end=str(r.index[-1].date()),
        n_days=len(r),
        total_return=float(equity.iloc[-1] - 1.0),
        cagr=float(equity.iloc[-1] ** (1.0 / yrs) - 1.0) if equity.iloc[-1] > 0 else -1.0,
        vol=vol,
        downside_vol=dvol,
        sharpe=float(ex.mean() / r.std(ddof=1) * np.sqrt(periods)) if r.std(ddof=1) > 0 else np.nan,
        sortino=float(ex.mean() * periods / dvol) if dvol and dvol > 0 else np.nan,
        max_drawdown=max_dd,
        calmar=float((equity.iloc[-1] ** (1.0 / yrs) - 1.0) / abs(max_dd)) if max_dd < 0 else np.nan,
        max_dd_days=max_dd_days,
        time_under_water=tuw,
        # Fraction of sessions that beat cash, not that were merely positive.
        # For a capacity-constrained book holding most of its equity in bills,
        # the latter is close to 100% and says nothing about the strategy.
        hit_rate=float((ex > 0).mean()),
        skew=float(r.skew()),
        kurtosis=float(r.kurtosis()),
        worst_day=float(r.min()),
        best_day=float(r.max()),
        var_95=float(r.quantile(0.05)),
        cvar_95=float(r[r <= r.quantile(0.05)].mean()),
        avg_gross=float(gross.mean()) if gross is not None else np.nan,
        avg_net=float(net.mean()) if net is not None else np.nan,
        turnover_annual=float(turnover.mean() * periods) if turnover is not None else np.nan,
        alpha_annual=alpha_a,
        alpha_t=alpha_t,
        beta=beta,
        r2=r2,
        information_ratio=ir,
    )


def newey_west_t(x: pd.Series, lags: int = 5) -> float:
    """t-statistic of the mean under Newey-West autocorrelation correction."""
    a = x.dropna().to_numpy(dtype=float)
    n = len(a)
    if n < 10:
        return np.nan
    e = a - a.mean()
    s = float(e @ e / n)
    for L in range(1, lags + 1):
        w = 1.0 - L / (lags + 1.0)
        s += 2.0 * w * float(e[L:] @ e[:-L] / n)
    return float(a.mean() / np.sqrt(max(s, 1e-18) / n))


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_ppf(p: float) -> float:
    # Acklam's rational approximation; adequate for the significance levels used.
    a = [-3.969683028665376e01, 2.209460984245205e02, -2.759285104469687e02,
         1.383577518672690e02, -3.066479806614716e01, 2.506628277459239e00]
    b = [-5.447609879822406e01, 1.615858368580409e02, -1.556989798598866e02,
         6.680131188771972e01, -1.328068155288572e01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e00,
         -2.549732539343734e00, 4.374664141464968e00, 2.938163982698783e00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e00,
         3.754408661907416e00]
    pl, ph = 0.02425, 1 - 0.02425
    if p < pl:
        q = np.sqrt(-2 * np.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if p > ph:
        q = np.sqrt(-2 * np.log(1 - p))
        return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    q = p - 0.5
    r = q * q
    return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)


def probabilistic_sharpe(sr: float, n: int, skew: float, kurt: float, sr_benchmark: float = 0.0) -> float:
    """Bailey & Lopez de Prado PSR: P(true Sharpe > benchmark) given the
    observed higher moments. `sr` and `sr_benchmark` are per-period."""
    denom = np.sqrt(max(1.0 - skew * sr + (kurt - 1.0) / 4.0 * sr**2, 1e-12))
    z = (sr - sr_benchmark) * np.sqrt(max(n - 1, 1)) / denom
    return float(_norm_cdf(z))


def deflated_sharpe(
    sr_annual: float,
    returns: pd.Series,
    n_trials: int,
    sr_dispersion_annual: float | None = None,
    periods: int = TRADING_DAYS,
) -> tuple[float, float]:
    """Deflated Sharpe ratio, returning (DSR, the benchmark Sharpe deflated to).

    `sr_dispersion_annual` is the standard deviation of Sharpe ratios across
    the trials actually run. When it is not supplied the conventional Lo
    (2002) standard error sqrt((1+SR^2/2)/n) is used, which is a materially
    harsher and more honest default than assuming trials were near-identical.
    """
    r = returns.dropna()
    n = len(r)
    sr_p = sr_annual / np.sqrt(periods)
    if sr_dispersion_annual is None:
        sr_dispersion_annual = float(np.sqrt((1.0 + 0.5 * sr_annual**2) / max(n, 2)) * np.sqrt(periods))
    v = sr_dispersion_annual / np.sqrt(periods)

    e = 0.5772156649015329
    m = max(int(n_trials), 2)
    sr0 = v * ((1 - e) * _norm_ppf(1 - 1.0 / m) + e * _norm_ppf(1 - 1.0 / (m * math.e)))
    dsr = probabilistic_sharpe(sr_p, n, float(r.skew()), float(r.kurtosis()) + 3.0, sr0)
    return dsr, float(sr0 * np.sqrt(periods))


def stationary_bootstrap(
    returns: pd.Series, n_paths: int = 2000, mean_block: int = 10, seed: int = 7
) -> pd.DataFrame:
    """Politis-Romano stationary bootstrap of a return series.

    Geometric block lengths preserve the short-horizon autocorrelation that a
    naive iid bootstrap destroys -- which matters here because intraday
    strategies have strongly autocorrelated volatility.
    """
    rng = np.random.default_rng(seed)
    a = returns.dropna().to_numpy(dtype=float)
    n = len(a)
    p = 1.0 / max(mean_block, 1)
    idx = np.empty((n_paths, n), dtype=np.int64)
    cur = rng.integers(0, n, size=n_paths)
    for t in range(n):
        idx[:, t] = cur
        newblock = rng.random(n_paths) < p
        cur = np.where(newblock, rng.integers(0, n, size=n_paths), (cur + 1) % n)
    paths = a[idx]
    cum = np.prod(1.0 + paths, axis=1)
    mu, sd = paths.mean(axis=1), paths.std(axis=1, ddof=1)
    sharpe = np.where(sd > 0, mu / sd * np.sqrt(TRADING_DAYS), np.nan)
    eq = np.cumprod(1.0 + paths, axis=1)
    dd = (eq / np.maximum.accumulate(eq, axis=1) - 1.0).min(axis=1)
    return pd.DataFrame({"total_return": cum - 1.0, "sharpe": sharpe, "max_drawdown": dd})

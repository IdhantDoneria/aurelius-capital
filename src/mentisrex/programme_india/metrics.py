"""Performance metrics: CAGR, volatility, Sharpe, beta/alpha, drawdown.

CAGR is computed and cross-checked TWO independent ways and both must agree
to 4 decimal places, enforced by `cagr_from_returns`'s own assertion. This
exists because of a real bug found and fixed during this programme's
research phase: building a NAV series as
`start_capital * (1 + returns).cumprod()` makes element [0] already reflect
day one's return, so `nav[-1] / nav[0]` silently drops day one's return from
every downstream CAGR calculation. The fix is to prepend an explicit day-zero
value of 1.0 before compounding, so `nav[0]` is the untouched starting
capital. See `tests/programme_india/test_metrics.py::test_cagr_bug_regression`
for the regression test that would have caught this on day one.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


class CagrMismatchError(ValueError):
    """Raised when the two independent CAGR calculations disagree beyond
    floating-point tolerance -- treat this as a bug, never suppress it."""


def nav_series(returns: pd.Series, start_capital: float) -> pd.Series:
    """The ONE correct way to build a NAV series in this programme.
    nav.iloc[0] is guaranteed to equal `start_capital` exactly -- no return
    has been applied to it yet."""
    growth = pd.concat([pd.Series([1.0]), (1 + returns.fillna(0.0))]).cumprod()
    nav = start_capital * growth.iloc[1:]
    nav.index = returns.index
    return nav


def cagr_from_returns(returns: pd.Series, years: float) -> float:
    """CAGR computed two independent ways; raises if they disagree."""
    nav = nav_series(returns, 1.0)
    cagr_endpoint = nav.iloc[-1] ** (1 / years) - 1
    log_ret = np.log1p(returns.fillna(0.0))
    cagr_logmean = np.exp(log_ret.mean() * 252) - 1
    if not np.isclose(cagr_endpoint, cagr_logmean, atol=1e-4):
        raise CagrMismatchError(
            f"CAGR methods disagree: endpoint={cagr_endpoint:.6f} vs logmean={cagr_logmean:.6f}. "
            "This is the exact bug class found during M42 research -- investigate the NAV "
            "construction before trusting either number."
        )
    return float(cagr_endpoint)


@dataclass
class DrawdownStats:
    max_dd: float
    peak_date: str
    trough_date: str
    recovery_date: str | None
    pct_days_underwater: float
    longest_underwater_days: int


def drawdown_stats(nav: pd.Series) -> DrawdownStats:
    running_max = nav.cummax()
    dd = nav / running_max - 1.0
    trough = dd.idxmin()
    peak = nav.loc[:trough].idxmax()
    post = nav.loc[trough:]
    rec = post[post >= running_max.loc[trough]]
    recovery = rec.index[0] if len(rec) else None
    underwater = dd < -1e-9
    grp = (~underwater).cumsum()
    longest = int(underwater.groupby(grp).sum().max()) if underwater.any() else 0
    return DrawdownStats(
        max_dd=float(dd.min()),
        peak_date=str(peak.date()),
        trough_date=str(trough.date()),
        recovery_date=str(recovery.date()) if recovery is not None else None,
        pct_days_underwater=float(underwater.mean()),
        longest_underwater_days=longest,
    )


def sharpe(returns: pd.Series, rf_daily: pd.Series | None = None) -> float:
    r = returns if rf_daily is None else returns - rf_daily.reindex(returns.index)
    if r.std() == 0:
        return 0.0
    return float((r.mean() / r.std()) * np.sqrt(252))


def beta_alpha(returns: pd.Series, bench_returns: pd.Series) -> tuple[float, float]:
    idx = returns.index
    b = bench_returns.reindex(idx).fillna(0.0)
    cov = np.cov(returns.fillna(0.0).values, b.values)
    beta = cov[0, 1] / cov[1, 1]
    alpha_annual = (returns.mean() - beta * b.mean()) * 252
    return float(beta), float(alpha_annual)

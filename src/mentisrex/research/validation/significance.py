"""Statistical significance primitives (AIDP M9).

Pure, deterministic functions over a return series. No look-ahead: everything is a
function of the realized in-sample returns only. Student-t p-values use a
self-contained regularized incomplete beta (scipy is not a dependency).

References:
  - Lo (2002) "The Statistics of Sharpe Ratios", Financial Analysts Journal.
  - Press et al., Numerical Recipes (incomplete beta continued fraction).
"""

from __future__ import annotations

import math

import numpy as np

TRADING_DAYS = 252


# ── regularized incomplete beta → Student-t p-value ─────────────────────────────

def _betacf(a: float, b: float, x: float) -> float:
    tiny = 1e-30
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    d = tiny if abs(d) < tiny else d
    d = 1.0 / d
    h = d
    for m in range(1, 200):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = tiny if abs(d) < tiny else d
        c = 1.0 + aa / c
        c = tiny if abs(c) < tiny else c
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = tiny if abs(d) < tiny else d
        c = 1.0 + aa / c
        c = tiny if abs(c) < tiny else c
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 3e-12:
            break
    return h


def betainc(a: float, b: float, x: float) -> float:
    """Regularized incomplete beta I_x(a,b)."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    lb = (math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
          + a * math.log(x) + b * math.log1p(-x))
    front = math.exp(lb)
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def student_t_two_sided_p(t: float, df: float) -> float:
    """Two-sided p-value for a t-statistic with df degrees of freedom."""
    if df <= 0:
        return float("nan")
    x = df / (df + t * t)
    return betainc(df / 2.0, 0.5, x)  # = 2 * P(T > |t|)


def normal_cdf(z: float) -> float:
    return 0.5 * math.erfc(-z / math.sqrt(2.0))


# ── moments ─────────────────────────────────────────────────────────────────────

def moments(returns) -> dict:
    r = np.asarray(returns, dtype=float)
    n = r.size
    if n < 2:
        return {"n": n, "mean": float(r.mean()) if n else 0.0, "std": 0.0,
                "skew": 0.0, "kurtosis": 0.0, "tail_ratio": 0.0}
    mean = float(r.mean())
    std = float(r.std(ddof=1))
    sd0 = r.std(ddof=0)
    skew = float((((r - mean) / sd0) ** 3).mean()) if sd0 > 0 else 0.0
    kurt = float((((r - mean) / sd0) ** 4).mean() - 3.0) if sd0 > 0 else 0.0
    p95, p05 = np.percentile(r, 95), np.percentile(r, 5)
    tail = float(abs(p95) / abs(p05)) if p05 != 0 else 0.0
    return {"n": n, "mean": mean, "std": std, "skew": skew, "kurtosis": kurt, "tail_ratio": tail}


# ── Sharpe + significance ───────────────────────────────────────────────────────

def sharpe(returns, periods: int = TRADING_DAYS, rf: float = 0.0) -> float:
    r = np.asarray(returns, dtype=float)
    if r.size < 2:
        return 0.0
    excess = r - rf / periods
    sd = excess.std(ddof=1)
    return float(excess.mean() / sd * math.sqrt(periods)) if sd > 0 else 0.0


def sharpe_standard_error(returns, periods: int = TRADING_DAYS) -> float:
    """Lo (2002) SR standard error with skew/kurtosis correction, annualized."""
    m = moments(returns)
    n = m["n"]
    if n < 3:
        return float("nan")
    sr = sharpe(returns, periods) / math.sqrt(periods)  # per-period SR
    var = (1 + 0.5 * sr**2 - m["skew"] * sr + (m["kurtosis"]) / 4.0 * sr**2) / (n - 1)
    return float(math.sqrt(max(var, 0.0)) * math.sqrt(periods))


def significance(returns, periods: int = TRADING_DAYS, *, hac_lag: int | None = None) -> dict:
    """t-stat, p-value, SE, mean CI, effect size, distribution diagnostics.

    Includes additive HAC (Newey-West) fields (`hac_se`, `hac_t_stat`,
    `hac_p_value`, `hac_lag`) alongside the IID ones so autocorrelation-robust
    significance is available without breaking existing IID consumers.
    """
    from mentisrex.research.validation.hac import hac_significance

    r = np.asarray(returns, dtype=float)
    m = moments(returns)
    n = m["n"]
    if n < 2 or m["std"] == 0:
        return {**m, "t_stat": 0.0, "p_value": 1.0, "standard_error": 0.0,
                "ci_low": 0.0, "ci_high": 0.0, "effect_size": 0.0,
                "sharpe": 0.0, "sharpe_se": float("nan"),
                **hac_significance(r, hac_lag)}
    se = m["std"] / math.sqrt(n)
    t = m["mean"] / se
    p = student_t_two_sided_p(t, n - 1)
    tcrit = 1.96  # normal approx for the mean CI half-width
    return {
        **m,
        "t_stat": float(t),
        "p_value": float(p),
        "standard_error": float(se),
        "ci_low": float(m["mean"] - tcrit * se),
        "ci_high": float(m["mean"] + tcrit * se),
        "effect_size": float(m["mean"] / m["std"]),   # Cohen's d
        "sharpe": sharpe(returns, periods),
        "sharpe_se": sharpe_standard_error(returns, periods),
        **hac_significance(r, hac_lag),
    }


def jackknife(returns, stat_fn) -> dict:
    """Leave-one-out jackknife estimate + bias + SE of an arbitrary statistic."""
    r = np.asarray(returns, dtype=float)
    n = r.size
    if n < 3:
        return {"estimate": float("nan"), "bias": float("nan"), "se": float("nan")}
    full = stat_fn(r)
    loo = np.array([stat_fn(np.delete(r, i)) for i in range(n)])
    mean_loo = loo.mean()
    bias = (n - 1) * (mean_loo - full)
    se = math.sqrt((n - 1) / n * float(((loo - mean_loo) ** 2).sum()))
    return {"estimate": float(n * full - (n - 1) * mean_loo), "bias": float(bias), "se": float(se)}

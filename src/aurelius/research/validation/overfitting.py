"""Overfitting analysis (AIDP M9).

Deflated & Probabilistic Sharpe Ratio (Bailey & López de Prado 2014), Probability
of Backtest Overfitting via CSCV (Bailey et al. 2017), and White's Reality Check
(White 2000). PSR/DSR work on a single track record; PBO/Reality-Check/SPA require
a *matrix* of candidate-configuration returns (e.g. from a parameter sweep) — when
that isn't available the engine records the method as skipped with the reason,
never a weaker substitute (see the module docstring in engine.py).

References:
  - Bailey & López de Prado (2014) "The Deflated Sharpe Ratio", J. Portfolio Mgmt.
  - Bailey, Borwein, López de Prado, Zhu (2017) "The Probability of Backtest
    Overfitting", J. Computational Finance (CSCV).
  - White (2000) "A Reality Check for Data Snooping", Econometrica.
"""

from __future__ import annotations

import math
from itertools import combinations

import numpy as np

from aurelius.research.validation.significance import moments, normal_cdf

_EULER = 0.5772156649015329


def inverse_normal(p: float) -> float:
    """Acklam's rational approximation of the standard-normal quantile."""
    if p <= 0:
        return -math.inf
    if p >= 1:
        return math.inf
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if p > phigh:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    q = p - 0.5
    r = q * q
    return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)


def _psr(sr_hat: float, sr_ref: float, n: int, skew: float, kurt_excess: float) -> float:
    """Probabilistic Sharpe Ratio: P(true SR > sr_ref). All SR are per-period."""
    denom = 1.0 - skew * sr_hat + (kurt_excess + 3.0 - 1.0) / 4.0 * sr_hat**2
    if denom <= 0 or n < 2:
        return float("nan")
    return normal_cdf((sr_hat - sr_ref) * math.sqrt(n - 1) / math.sqrt(denom))


def probabilistic_sharpe_ratio(returns, *, sr_benchmark: float = 0.0) -> dict:
    m = moments(returns)
    n = m["n"]
    if n < 3 or m["std"] == 0:
        return {"psr": float("nan"), "n": n}
    sr_hat = m["mean"] / m["std"]                    # per-period Sharpe
    return {"psr": _psr(sr_hat, sr_benchmark, n, m["skew"], m["kurtosis"]),
            "sr_per_period": sr_hat, "n": n}


def deflated_sharpe_ratio(returns, *, n_trials: int, sr_variance: float | None = None) -> dict:
    """DSR: PSR against the *expected maximum* Sharpe from n_trials independent
    trials. `sr_variance` = variance of SR estimates across the trials; if unknown
    (single track record) we substitute the estimator's own sampling variance and
    flag it — an explicit, documented approximation, not a silent one."""
    m = moments(returns)
    n = m["n"]
    if n < 3 or m["std"] == 0:
        return {"dsr": float("nan"), "n": n, "n_trials": n_trials}
    sr_hat = m["mean"] / m["std"]
    substituted = sr_variance is None
    if substituted:
        sr_variance = (1 - m["skew"] * sr_hat + (m["kurtosis"] + 2) / 4.0 * sr_hat**2) / (n - 1)
    v = max(sr_variance, 1e-12)
    N = max(n_trials, 2)
    sr0 = math.sqrt(v) * ((1 - _EULER) * inverse_normal(1 - 1.0 / N)
                          + _EULER * inverse_normal(1 - 1.0 / (N * math.e)))
    return {"dsr": _psr(sr_hat, sr0, n, m["skew"], m["kurtosis"]),
            "sr0_expected_max": sr0, "sr_per_period": sr_hat, "n_trials": N,
            "sr_variance_substituted": substituted}


def pbo_cscv(returns_matrix, *, n_splits: int = 10) -> dict:
    """Probability of Backtest Overfitting via Combinatorially Symmetric CV.
    returns_matrix: shape (T, N) — T periods × N candidate configurations.
    Requires N ≥ 2 configs; returns insufficient_data otherwise."""
    R = np.asarray(returns_matrix, dtype=float)
    if R.ndim != 2 or R.shape[1] < 2 or R.shape[0] < 2 * n_splits:
        return {"insufficient_data": True, "reason": "need (T>=2S, N>=2) config matrix"}
    T, N = R.shape
    S = n_splits - (n_splits % 2)
    bounds = np.linspace(0, T, S + 1, dtype=int)
    blocks = [np.arange(bounds[i], bounds[i + 1]) for i in range(S)]

    def sr(x):
        sd = x.std(ddof=1)
        return x.mean() / sd if sd > 0 else 0.0

    logits = []
    for combo in combinations(range(S), S // 2):
        is_idx = np.concatenate([blocks[i] for i in combo])
        oos_idx = np.concatenate([blocks[i] for i in range(S) if i not in combo])
        is_sr = np.array([sr(R[is_idx, j]) for j in range(N)])
        oos_sr = np.array([sr(R[oos_idx, j]) for j in range(N)])
        best = int(np.argmax(is_sr))
        rank = (np.sum(oos_sr <= oos_sr[best])) / (N + 1)       # relative OOS rank
        rank = min(max(rank, 1e-6), 1 - 1e-6)
        logits.append(math.log(rank / (1 - rank)))
    logits = np.array(logits)
    return {"pbo": float((logits <= 0).mean()), "n_combinations": int(logits.size),
            "median_logit": float(np.median(logits))}


def whites_reality_check(excess_matrix, *, n_boot: int = 1000, block: int = 20,
                         seed: int = 0) -> dict:
    """White's Reality Check: H0 = best of N strategies is no better than benchmark.
    excess_matrix: (T, N) excess returns over the benchmark. Stationary-bootstrap
    the max mean statistic."""
    X = np.asarray(excess_matrix, dtype=float)
    if X.ndim != 2 or X.shape[1] < 1 or X.shape[0] < 3:
        return {"insufficient_data": True, "reason": "need (T, N) excess matrix"}
    from aurelius.research.validation.bootstrap import _resample
    T, N = X.shape
    means = X.mean(axis=0)
    v_obs = math.sqrt(T) * means.max()
    rng = np.random.default_rng(seed)
    idx = np.arange(T)
    null = np.empty(n_boot)
    for b in range(n_boot):
        resampled = _resample(idx.astype(float), "stationary", block, rng).astype(int)
        bmeans = X[resampled].mean(axis=0)
        null[b] = math.sqrt(T) * (bmeans - means).max()
    return {"reality_check_p": float((null >= v_obs).mean()), "statistic": float(v_obs),
            "n_strategies": int(N)}

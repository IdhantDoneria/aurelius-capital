"""HAC (Newey-West) standard errors for the mean of a return series (M31).

Pure, deterministic. The IID standard error `std/√n` in `significance.py` assumes
serially uncorrelated returns. Momentum / overlapping-horizon strategies violate
that: positive autocorrelation makes the IID SE too small, inflating t-stats and
p-values and biasing the promotion gate toward false positives. Newey-West (1987)
corrects the long-run variance with a Bartlett-kernel-weighted sum of
autocovariances.

References:
  - Newey & West (1987), Econometrica 55(3).
  - Newey & West (1994) automatic lag selection: L = floor(4 * (n/100)^(2/9)).
"""

from __future__ import annotations

import math

import numpy as np


def auto_lag(n: int) -> int:
    """Newey-West (1994) automatic Bartlett lag. Non-negative, < n."""
    if n < 2:
        return 0
    return min(n - 1, int(math.floor(4.0 * (n / 100.0) ** (2.0 / 9.0))))


def hac_long_run_variance(returns, lag: int | None = None) -> float:
    """Newey-West long-run variance of the mean estimator (per-period, unscaled).

    Returns the HAC estimate of Var(mean) * n — i.e. gamma_0 + 2*sum_k w_k*gamma_k
    with Bartlett weights w_k = 1 - k/(lag+1). Falls back to the sample variance
    when lag=0 or n<2.
    """
    r = np.asarray(returns, dtype=float)
    n = r.size
    if n < 2:
        return 0.0
    if lag is None:
        lag = auto_lag(n)
    lag = max(0, min(lag, n - 1))
    e = r - r.mean()
    # gamma_0 uses 1/n (not ddof) so lag=0 reproduces the population variance;
    # the (n-1) small-sample correction is applied by the caller's SE where needed.
    gamma0 = float(np.dot(e, e) / n)
    lrv = gamma0
    for k in range(1, lag + 1):
        w = 1.0 - k / (lag + 1.0)
        gamma_k = float(np.dot(e[k:], e[:-k]) / n)
        lrv += 2.0 * w * gamma_k
    return max(lrv, 0.0)


def hac_standard_error(returns, lag: int | None = None) -> float:
    """Newey-West standard error of the sample mean. NaN if n < 2."""
    r = np.asarray(returns, dtype=float)
    n = r.size
    if n < 2:
        return float("nan")
    lrv = hac_long_run_variance(r, lag)
    return float(math.sqrt(lrv / n))


def hac_significance(returns, lag: int | None = None) -> dict:
    """HAC mean t-stat + two-sided p-value. Uses the Student-t reference with
    (n-1) df, matching `significance()`'s IID path so the two are comparable."""
    from mentisrex.research.validation.significance import student_t_two_sided_p

    r = np.asarray(returns, dtype=float)
    n = r.size
    used_lag = auto_lag(n) if lag is None else max(0, min(lag, max(n - 1, 0)))
    se = hac_standard_error(r, lag)
    if n < 2 or not math.isfinite(se) or se == 0.0:
        return {"hac_se": 0.0 if n >= 2 else float("nan"),
                "hac_t_stat": 0.0, "hac_p_value": 1.0, "hac_lag": used_lag}
    t = float(r.mean()) / se
    return {"hac_se": float(se), "hac_t_stat": float(t),
            "hac_p_value": float(student_t_two_sided_p(t, n - 1)),
            "hac_lag": used_lag}

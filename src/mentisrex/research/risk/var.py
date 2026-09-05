"""Value-at-Risk & Expected Shortfall (AIDP M13).

Historical and parametric (Gaussian) VaR + ES at 95 / 97.5 / 99%. Deterministic —
historical VaR is an empirical quantile of the supplied return series; parametric
uses the closed-form normal quantile (hard-coded z-scores, no scipy). Returns are
reported as positive loss fractions. Horizon scaling by √t.
"""

from __future__ import annotations

import numpy as np

from mentisrex.research.risk.models import VaRReport

CONFIDENCES = (0.95, 0.975, 0.99)
_Z = {0.95: 1.6448536269514722, 0.975: 1.959963984540054, 0.99: 2.3263478740408408}


def historical_var(returns, *, confidences=CONFIDENCES, horizon_days: int = 1) -> VaRReport:
    r = np.asarray(returns, dtype=float)
    scale = np.sqrt(horizon_days)
    var, es = {}, {}
    if r.size == 0:
        var = dict.fromkeys(confidences, 0.0)
        es = dict(var)
    else:
        for c in confidences:
            q = np.quantile(r, 1 - c)  # left-tail return
            var[c] = float(max(-q, 0.0) * scale)
            tail = r[r <= q]
            es[c] = float(max(-tail.mean(), 0.0) * scale) if tail.size else var[c]
    vol = float(r.std(ddof=1)) if r.size > 1 else 0.0
    return VaRReport(
        method="historical",
        horizon_days=horizon_days,
        var=_key(var),
        expected_shortfall=_key(es),
        volatility=vol,
    )


def parametric_var(returns, *, confidences=CONFIDENCES, horizon_days: int = 1) -> VaRReport:
    r = np.asarray(returns, dtype=float)
    mu = float(r.mean()) if r.size else 0.0
    sigma = float(r.std(ddof=1)) if r.size > 1 else 0.0
    scale = np.sqrt(horizon_days)
    var, es = {}, {}
    for c in confidences:
        z = _Z.get(c, _Z[0.95])
        var[c] = float(max(z * sigma - mu, 0.0) * scale)
        # Gaussian ES: φ(z)/(1-c)·σ
        pdf = np.exp(-0.5 * z * z) / np.sqrt(2 * np.pi)
        es[c] = float(max(pdf / (1 - c) * sigma - mu, 0.0) * scale)
    return VaRReport(
        method="parametric",
        horizon_days=horizon_days,
        var=_key(var),
        expected_shortfall=_key(es),
        volatility=sigma,
    )


def _key(d: dict) -> dict:
    return {f"{int(c * 1000) / 10:g}%": v for c, v in d.items()}

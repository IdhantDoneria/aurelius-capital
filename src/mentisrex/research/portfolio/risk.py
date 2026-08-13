"""Portfolio risk diagnostics (AIDP M10).

Return / risk / marginal-risk contributions, concentration, effective number of
holdings, and the largest single-name risk contribution. Pure linear algebra over
(weights, covariance, expected returns).
"""

from __future__ import annotations

import numpy as np


def risk_diagnostics(weights, cov, mu=None) -> dict:
    w = np.asarray(weights, dtype=float)
    cov = np.asarray(cov, dtype=float)
    port_var = float(w @ cov @ w)
    port_vol = float(np.sqrt(max(port_var, 0.0)))

    marginal = cov @ w                                   # ∂σ²/∂w (unscaled)
    marginal_risk = marginal / port_vol if port_vol > 0 else np.zeros_like(w)  # ∂σ/∂w
    risk_contribution = w * marginal_risk                # RC_i, Σ RC = σ
    pct_risk = (risk_contribution / port_vol) if port_vol > 0 else np.zeros_like(w)

    gross = np.abs(w).sum() or 1.0
    shares = np.abs(w) / gross
    herfindahl = float((shares**2).sum())

    out = {
        "volatility": port_vol,
        "variance": port_var,
        "effective_holdings": float(1.0 / herfindahl) if herfindahl > 0 else 0.0,
        "concentration_herfindahl": herfindahl,
        "max_weight": float(np.abs(w).max()) if w.size else 0.0,
        "risk_contribution": risk_contribution.tolist(),
        "pct_risk_contribution": pct_risk.tolist(),
        "marginal_risk_contribution": marginal_risk.tolist(),
        "max_risk_contribution": float(np.abs(risk_contribution).max()) if w.size else 0.0,
        "avg_correlation": _avg_correlation(cov),
    }
    if mu is not None:
        mu = np.asarray(mu, dtype=float)
        rc = w * mu
        out["expected_return"] = float(w @ mu)
        out["return_contribution"] = rc.tolist()
        out["max_return_contribution"] = float(np.abs(rc).max()) if w.size else 0.0
    return out


def diagonal_risk_diagnostics(weights, var, mu=None) -> dict:
    """O(N) risk diagnostics for a diagonal (uncorrelated) risk model — avoids
    materializing a dense N×N covariance for large universes."""
    w = np.asarray(weights, dtype=float)
    var = np.clip(np.asarray(var, dtype=float), 1e-16, None)
    port_var = float((w**2 * var).sum())
    vol = float(np.sqrt(max(port_var, 0.0)))
    marginal = (w * var) / vol if vol > 0 else np.zeros_like(w)
    rc = w * marginal
    pct = rc / vol if vol > 0 else np.zeros_like(w)
    gross = np.abs(w).sum() or 1.0
    shares = np.abs(w) / gross
    herf = float((shares**2).sum())
    out = {
        "volatility": vol, "variance": port_var,
        "effective_holdings": float(1.0 / herf) if herf > 0 else 0.0,
        "concentration_herfindahl": herf,
        "max_weight": float(np.abs(w).max()) if w.size else 0.0,
        "risk_contribution": rc.tolist(), "pct_risk_contribution": pct.tolist(),
        "marginal_risk_contribution": marginal.tolist(),
        "max_risk_contribution": float(np.abs(rc).max()) if w.size else 0.0,
        "avg_correlation": 0.0,             # diagonal model ⇒ zero cross-correlation
    }
    if mu is not None:
        mu = np.asarray(mu, dtype=float)
        out["expected_return"] = float(w @ mu)
        out["return_contribution"] = (w * mu).tolist()
        out["max_return_contribution"] = float(np.abs(w * mu).max()) if w.size else 0.0
    return out


def _avg_correlation(cov) -> float:
    d = np.sqrt(np.clip(np.diag(cov), 1e-16, None))
    corr = cov / np.outer(d, d)
    n = corr.shape[0]
    if n < 2:
        return 0.0
    iu = np.triu_indices(n, k=1)
    return float(np.mean(corr[iu]))

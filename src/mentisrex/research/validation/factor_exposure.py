"""Risk / factor exposure (AIDP M9).

Market beta + annualized alpha via OLS of strategy returns on a benchmark. Style
tilts (size/value/quality/…) are read from the M6 research matrix features of
the held names when positions + matrix are supplied. Sector / industry / country /
currency exposures need a classification map that the PIT stack does not yet carry —
reported as insufficient_data with the unblocking requirement, never guessed.
"""

from __future__ import annotations

import math

import numpy as np


def market_exposure(returns, benchmark_returns, *, periods: int = 252) -> dict:
    r = np.asarray(returns, dtype=float)
    b = np.asarray(benchmark_returns, dtype=float) if benchmark_returns is not None else None
    if b is None or b.size < 2 or r.size < 2:
        return {"insufficient_data": True, "reason": "no benchmark returns"}
    n = min(r.size, b.size)
    r, b = r[:n], b[:n]
    var_b = b.var(ddof=0)
    if var_b == 0:
        return {"insufficient_data": True, "reason": "zero-variance benchmark"}
    beta = float(np.cov(r, b, ddof=0)[0, 1] / var_b)
    alpha_daily = float(r.mean() - beta * b.mean())
    corr = float(np.corrcoef(r, b)[0, 1])
    return {"market_beta": beta, "annualized_alpha": alpha_daily * periods,
            "correlation": corr, "r_squared": corr**2}


def style_exposure(positions, research_matrix, *, features=None) -> dict:
    """Weighted average of matrix feature values across held names — the portfolio's
    style tilt. positions: {security_id: weight}. Needs the M6 matrix."""
    if not positions or research_matrix is None:
        return {"insufficient_data": True, "reason": "need positions + research matrix"}
    frame = research_matrix.frame
    cols = features or list(frame.columns)
    total_w = sum(abs(w) for w in positions.values()) or 1.0
    tilt = {}
    for col in cols:
        acc, wsum = 0.0, 0.0
        for sid, w in positions.items():
            if sid in frame.index and col in frame.columns:
                val = frame.loc[sid, col]
                if val is not None and not (isinstance(val, float) and math.isnan(val)):
                    acc += w * float(val)
                    wsum += abs(w)
        tilt[col] = acc / total_w if wsum else None
    return {"style_tilt": tilt}


def concentration(positions) -> dict:
    """Herfindahl concentration + top-name share of gross exposure."""
    if not positions:
        return {"insufficient_data": True}
    w = np.array([abs(x) for x in positions.values()], dtype=float)
    gross = w.sum() or 1.0
    shares = w / gross
    return {"herfindahl": float((shares**2).sum()), "n_names": int(w.size),
            "top_name_share": float(shares.max()), "effective_names": float(1.0 / (shares**2).sum())}


def unsupported_exposures() -> dict:
    """Sector/industry/country/currency need a classification map absent from the
    PIT stack today (unblock: add GICS/country to SecurityMaster — M2 extension)."""
    # `supported: False` (not insufficient_data) — a permanent architecture gap, so it
    # must not count as an inconclusive-this-run analysis in the verdict.
    return {k: {"supported": False, "reason": "no classification map in SecurityMaster",
                "unblock": "add GICS sector/industry + country/currency to SecurityMaster"}
            for k in ("sector", "industry", "country", "currency")}

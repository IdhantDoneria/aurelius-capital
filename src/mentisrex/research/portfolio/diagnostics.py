"""Portfolio diagnostics assembly (AIDP M10).

Composes the risk engine with exposure/cost summaries into the diagnostics block
carried on a Portfolio. Pure — no construction, no side effects.
"""

from __future__ import annotations

import numpy as np

from mentisrex.research.portfolio.risk import risk_diagnostics


def build_diagnostics(
    weights, cov, mu=None, *, sectors=None, cost: dict | None = None, turnover: float | None = None
) -> dict:
    diag = risk_diagnostics(weights, cov, mu)
    if turnover is not None:
        diag["turnover"] = turnover
    if cost is not None:
        diag["cost"] = cost
    if sectors is not None:
        diag["sector_exposure"] = _group_exposure(weights, sectors)
    return diag


def _group_exposure(weights, groups) -> dict:
    w = np.asarray(weights, dtype=float)
    exposure: dict = {}
    for wi, g in zip(w, groups, strict=False):
        exposure[g] = exposure.get(g, 0.0) + float(wi)
    return exposure

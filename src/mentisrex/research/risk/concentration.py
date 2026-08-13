"""Concentration analytics (AIDP M13).

HHI, effective number of holdings, largest position and largest risk contribution,
top-5 weight. The risk-contribution input comes from M10 `risk_diagnostics`
(reused by the engine) — this module only aggregates the weight geometry.
"""

from __future__ import annotations

import numpy as np

from mentisrex.research.risk.models import ConcentrationReport


def concentration_report(weights: dict, *, risk_contribution: dict | None = None) -> ConcentrationReport:
    w = np.array(list((weights or {}).values()), dtype=float)
    if w.size == 0:
        return ConcentrationReport(0.0, 0.0, 0.0, 0.0, 0.0)
    gross = np.abs(w).sum() or 1.0
    shares = np.abs(w) / gross
    hhi = float((shares ** 2).sum())
    top5 = float(np.sort(shares)[::-1][:5].sum())
    largest_rc = max((abs(v) for v in (risk_contribution or {}).values()), default=0.0)
    return ConcentrationReport(
        herfindahl=hhi, effective_holdings=float(1.0 / hhi) if hhi > 0 else 0.0,
        largest_weight=float(np.abs(w).max()), largest_contribution=float(largest_rc),
        top5_weight=top5)

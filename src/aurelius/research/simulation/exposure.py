"""Exposure & risk timeline (AIDP Phase 11).

Aggregate exposures over the run and build per-date risk snapshots (leverage,
concentration, rolling volatility). Sector/country/factor exposures are computed
when a classification map is injected; otherwise reported as unavailable (same
SecurityMaster gap noted in Phases 9–10).
"""

from __future__ import annotations

import numpy as np

from aurelius.research.simulation.models import ExposureReport, RiskSnapshot


def exposure_report(snapshots) -> ExposureReport:
    if not snapshots:
        return ExposureReport(0, 0, 0, 0, 0, 0)
    g = np.array([s.gross_exposure for s in snapshots])
    n = np.array([s.net_exposure for s in snapshots])
    lo = np.array([s.long_exposure for s in snapshots])
    sh = np.array([s.short_exposure for s in snapshots])
    cashw = np.array([1.0 - s.gross_exposure for s in snapshots])
    return ExposureReport(float(g.mean()), float(n.mean()), float(lo.mean()),
                          float(sh.mean()), float(cashw.mean()), float(g.max()))


def risk_timeline(snapshots, values, *, window: int = 63, periods: int = 252) -> list[RiskSnapshot]:
    v = np.asarray(values, dtype=float)
    out = []
    for i, s in enumerate(snapshots):
        if i >= 1:
            lo = max(0, i - window)
            seg = v[lo:i + 1]
            rr = seg[1:] / seg[:-1] - 1 if seg.size > 1 else np.array([])
            vol = float(rr.std(ddof=1) * np.sqrt(periods)) if rr.size > 1 else 0.0
        else:
            vol = 0.0
        w = np.array(list(s.holdings.values()), dtype=float)
        gross = np.abs(w).sum() or 1.0
        shares = np.abs(w) / gross
        hhi = float((shares**2).sum()) if w.size else 0.0
        out.append(RiskSnapshot(
            date=s.date, volatility=vol, gross_leverage=s.gross_exposure,
            net_leverage=s.net_exposure, concentration_hhi=hhi,
            largest_weight=float(np.abs(w).max()) if w.size else 0.0,
            effective_holdings=float(1.0 / hhi) if hhi > 0 else 0.0))
    return out

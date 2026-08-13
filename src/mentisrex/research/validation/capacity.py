"""Capacity & market-impact estimation (AIDP M9).

Square-root market-impact law: impact ≈ c · σ · sqrt(Q / ADV), the standard
practitioner model (Almgren et al. 2005). All estimates carry explicit assumptions;
when ADV isn't supplied we report a turnover-based qualitative signal rather than a
fabricated number.

Reference: Almgren, Thum, Hauptmann, Li (2005) "Direct Estimation of Equity Market
Impact", Risk.
"""

from __future__ import annotations

import math

import numpy as np


def capacity_analysis(pm, *, aum: float = 1e8, adv: float | None = None,
                      impact_coef: float = 0.1, target_participation: float = 0.10,
                      periods: int = 252) -> dict:
    """Estimate ADV utilisation, per-trade impact, implementation shortfall, and a
    capacity ceiling. `adv` = average daily $ volume of the traded names (scalar
    proxy); omit → qualitative turnover signal only."""
    rts = pm.round_trips or []
    ann_vol = float(pm.annualized_volatility) or 0.0
    daily_sigma = ann_vol / math.sqrt(periods) if ann_vol else 0.0

    if not rts:
        return {"insufficient_data": True, "reason": "no round trips"}
    notionals = np.array([abs(t.quantity * t.entry_price) for t in rts], dtype=float)
    avg_notional = float(notionals.mean())

    out = {"annual_turnover": float(pm.annual_turnover), "aum": aum,
           "avg_trade_notional": avg_notional}

    if adv is None or adv <= 0:
        out.update({"adv_supplied": False,
                    "capacity_signal": "high_turnover" if pm.annual_turnover > 5 else "moderate",
                    "reason": "ADV not supplied — impact/shortfall need per-name ADV"})
        return out

    participation = notionals / adv
    impact_bps = impact_coef * daily_sigma * np.sqrt(np.clip(participation, 0, None)) * 1e4
    shortfall = float((impact_bps / 1e4 * notionals).sum())
    # capacity ceiling: AUM scaled so mean participation hits the target
    scale = target_participation / max(float(participation.mean()), 1e-9)
    out.update({
        "adv_supplied": True,
        "adv_utilisation": float(participation.mean()),
        "max_participation": float(participation.max()),
        "avg_market_impact_bps": float(impact_bps.mean()),
        "implementation_shortfall": shortfall,
        "estimated_capacity_aum": float(aum * scale),
    })
    return out

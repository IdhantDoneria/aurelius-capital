"""Capacity engine (M40, §XXII) — how a factor's edge decays with AUM.

At small AUM a factor pays only linear costs; as AUM grows, each name's order
becomes a larger fraction of its ADV and square-root market impact (Almgren 2005)
eats the edge. This computes the AUM → net-Sharpe curve for a long-short factor
using the real per-name ADV panel, and reports the AUM at which net Sharpe halves.

Deterministic; reuses TransactionCostModel. Baskets are equal-weight top/bottom
quantile (same construction as evaluate_factor's long-short), so the capacity
number is consistent with the reported gross Sharpe.
"""

from __future__ import annotations

import numpy as np

from mentisrex.research.cross_sectional import percentile_rank
from mentisrex.research.validation.significance import sharpe


def _leg_returns_and_impact(signals, forward_returns, adv, *, q, aum, cost_model):
    """Per-rebalance net long-short return at a given AUM, charging linear + √-law
    impact from each leg's participation in name ADV."""
    lin = cost_model.linear_bps() / 1e4
    k = cost_model.impact_coef
    net_series = []
    for sig, fwd, adv_t in zip(signals, forward_returns, adv, strict=True):
        names = [n for n in sig if n in fwd and sig[n] == sig[n]]
        if len(names) < q:
            continue
        s = np.array([sig[n] for n in names], dtype=float)
        pr = percentile_rank(s)
        longs = [names[i] for i in range(len(names)) if pr[i] == pr[i] and pr[i] >= (q - 1) / q]
        shorts = [names[i] for i in range(len(names)) if pr[i] == pr[i] and pr[i] < 1.0 / q]
        if not longs or not shorts:
            continue
        gross = np.mean([fwd[n] for n in longs]) - np.mean([fwd[n] for n in shorts])
        # per-name notional = half the book split equally within each leg
        cost = 0.0
        for leg in (longs, shorts):
            notional = (aum / 2.0) / len(leg)
            for n in leg:
                a = adv_t.get(n, 0.0)
                part = notional / a if a and a > 0 else 1.0  # no ADV => punitive
                impact = k * np.sqrt(max(part, 0.0))
                cost += (lin + impact) * notional
        # cost as a fraction of gross book (AUM) — round-trip both legs
        net_series.append(gross - cost / aum)
    return np.array(net_series, dtype=float)


def capacity_curve(
    signals, forward_returns, adv, *, cost_model, q=5, aum_levels=None, periods_per_year=12
) -> dict:
    """AUM → net long-short Sharpe. `adv` is a list (per rebalance) of dict
    security_id -> average daily $ volume. Returns the curve plus the half-Sharpe
    capacity (AUM where net Sharpe first drops below half the small-AUM Sharpe)."""
    if aum_levels is None:
        aum_levels = [1e6, 5e6, 1e7, 5e7, 1e8, 5e8, 1e9]
    curve = []
    for aum in aum_levels:
        net = _leg_returns_and_impact(
            signals, forward_returns, adv, q=q, aum=aum, cost_model=cost_model
        )
        sh = sharpe(net, periods=periods_per_year) if net.size >= 2 else float("nan")
        curve.append(
            {
                "aum": float(aum),
                "net_sharpe": float(sh),
                "net_mean_period": float(net.mean()) if net.size else float("nan"),
            }
        )
    base = curve[0]["net_sharpe"]
    half_cap = None
    for pt in curve:
        if base == base and base > 0 and pt["net_sharpe"] < base / 2.0:
            half_cap = pt["aum"]
            break
    return {"curve": curve, "base_sharpe": float(base), "half_sharpe_capacity_usd": half_cap}

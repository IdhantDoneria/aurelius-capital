"""Liquidity risk (AIDP M13).

ADV participation, days-to-liquidate, and liquidity concentration from position
notionals and average daily dollar volume. Shares the participation notion with
the M10 cost model and M11 capacity analytics (same √-participation idea), applied
here to a *static* portfolio rather than a trade schedule.
"""

from __future__ import annotations

import numpy as np

from aurelius.research.risk.models import LiquidityReport


def liquidity_report(weights: dict, adv: dict, *, portfolio_value: float,
                     participation_limit: float = 0.10,
                     liquidation_days_threshold: float = 5.0) -> LiquidityReport:
    """`adv`: security_id -> average daily $ volume. Days-to-liquidate assumes you
    can trade `participation_limit` of ADV per day."""
    ids = [s for s in weights if weights[s] != 0]
    if not ids:
        return LiquidityReport(0.0, 0.0, {}, 0.0, 0.0, "ok")
    parts, days, illiquid_w = [], {}, 0.0
    for sid in ids:
        notional = abs(weights[sid]) * portfolio_value
        v = adv.get(sid, 0.0)
        if v and v > 0:
            part = notional / v
            d = part / participation_limit
        else:
            part, d = float("inf"), float("inf")
        parts.append(min(part, 1e9))
        days[sid] = float(min(d, 1e9))
        if d > liquidation_days_threshold:
            illiquid_w += abs(weights[sid])
    parts = np.array(parts, dtype=float)
    max_days = max(days.values())
    signal = ("ok" if max_days <= liquidation_days_threshold
              else "warning" if max_days <= 3 * liquidation_days_threshold else "critical")
    return LiquidityReport(
        avg_participation=float(np.mean(parts)), max_participation=float(np.max(parts)),
        days_to_liquidate=days, max_days_to_liquidate=float(max_days),
        illiquid_weight=float(illiquid_w), liquidity_signal=signal)

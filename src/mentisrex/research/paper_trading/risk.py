"""Pre-trade risk gate + kill switch (AIDP M12).

A minimal, dependency-injected guard the session runs before sending orders:
per-name weight cap, gross-leverage cap, and a manual kill switch. Post-trade
exposure/concentration analytics already live in M11 (`exposure`, `risk_timeline`)
and M9 (factor exposure) and are NOT duplicated here. Latency limits, margin, and
venue risk checks are documented production extensions.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RiskLimits:
    max_name_weight: float = 0.10
    max_gross_leverage: float = 1.05
    kill: bool = False                    # kill switch: block all order flow


class PreTradeRiskGate:
    def __init__(self, limits: RiskLimits | None = None) -> None:
        self.limits = limits or RiskLimits()

    def check(self, orders, state, prices) -> tuple[list, list]:
        """Return (approved_orders, rejections). An order is rejected if it would
        push a name past `max_name_weight` or gross past `max_gross_leverage`, or if
        the kill switch is set."""
        if self.limits.kill:
            return [], [(o, "kill_switch") for o in orders]
        value = state.total_value() or 1.0
        approved, rejected = [], []
        # project post-trade shares to test caps
        proj = {sid: h.shares for sid, h in state.holdings.items()}
        for o in orders:
            p = prices.get(o.security_id)
            if p is None or p <= 0:
                rejected.append((o, "unpriced"))
                continue
            new_shares = proj.get(o.security_id, 0.0) + o.quantity
            if abs(new_shares * p) / value > self.limits.max_name_weight + 1e-9:
                rejected.append((o, "name_weight_cap"))
                continue
            gross = (sum(abs(s) * prices.get(sid, 0.0) for sid, s in proj.items())
                     - abs(proj.get(o.security_id, 0.0) * p) + abs(new_shares * p))
            if gross / value > self.limits.max_gross_leverage + 1e-9:
                rejected.append((o, "gross_leverage_cap"))
                continue
            proj[o.security_id] = new_shares
            approved.append(o)
        return approved, rejected

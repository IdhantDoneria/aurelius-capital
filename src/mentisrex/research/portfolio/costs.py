"""Transaction cost model (AIDP M10).

Commission + half-spread + slippage (fixed bps) plus a non-linear market-impact
term following the square-root law: impact = k·√(order/ADV). All coefficients are
configurable; nothing is hard-coded into the optimizer.

Reference: Almgren et al. (2005) square-root market impact.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class TransactionCostModel:
    commission_bps: float = 1.0
    spread_bps: float = 2.0            # full spread; half is paid
    slippage_bps: float = 1.0
    impact_coef: float = 0.1           # k in k·√(participation)

    def linear_bps(self) -> float:
        return self.commission_bps + self.spread_bps / 2.0 + self.slippage_bps

    def estimate(self, trade_notionals, adv=None) -> dict:
        """Cost of a set of trades. `trade_notionals`: $ traded per name (array).
        `adv`: per-name average daily $ volume (array/scalar) → enables impact."""
        q = np.abs(np.asarray(trade_notionals, dtype=float))
        linear = self.linear_bps() / 1e4 * q
        if adv is not None:
            adv_arr = np.asarray(adv, dtype=float)
            participation = np.divide(q, adv_arr, out=np.zeros_like(q),
                                      where=adv_arr > 0)
            impact = self.impact_coef * np.sqrt(np.clip(participation, 0, None)) * q
        else:
            participation = np.zeros_like(q)
            impact = np.zeros_like(q)
        total = float((linear + impact).sum())
        turned = float(q.sum())
        return {
            "linear_cost": float(linear.sum()),
            "impact_cost": float(impact.sum()),
            "total_cost": total,
            "total_cost_bps": (total / turned * 1e4) if turned > 0 else 0.0,
            "avg_participation": float(participation.mean()) if participation.size else 0.0,
            "max_participation": float(participation.max()) if participation.size else 0.0,
        }

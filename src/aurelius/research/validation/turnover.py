"""Turnover & holding-period diagnostics (AIDP M9).

Extracts trading-intensity statistics from the certified PerformanceMetrics /
round-trips — does not recompute what the backtester already produced.
"""

from __future__ import annotations

import numpy as np


def turnover_profile(pm) -> dict:
    rts = pm.round_trips or []
    holds = np.array([t.holding_days for t in rts], dtype=float) if rts else np.array([])
    return {
        "annual_turnover": float(pm.annual_turnover),
        "avg_holding_days": float(pm.avg_holding_period_days),
        "median_holding_days": float(np.median(holds)) if holds.size else 0.0,
        "num_trades": int(pm.num_trades),
        "min_holding_days": float(holds.min()) if holds.size else 0.0,
        "max_holding_days": float(holds.max()) if holds.size else 0.0,
    }
